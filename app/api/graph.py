"""补丁 P1 图谱端点（`app/api/graph.py`）：只读查关系 + 单条关系 upsert。

两个端点同挂 `/api/graph/relations`，按 HTTP 方法区分：

  - `POST /api/graph/relations`（P1-1，**只读**）——按英雄查克制 / 搭档 / 出装 / 铭文。
  - `PUT  /api/graph/relations`（P1-3，**写**）——单条关系 upsert，本项目唯一的高危端点。

**为什么只读端点也在这里、不放进 `/api/chat`**：项目二要把能力包成细粒度 MCP 工具，
它需要「只查图谱」这个动作本身，而不是「问一句、顺带跑了图谱和检索」。既有
`/api/chat/sync` 是粗粒度入口，不改它（契约 §2-1）。

**P1-1 的 `relation` 取值直接取 `INTENT_TO_TEMPLATE` 的键**：契约要求这套名字必须与
项目一已对外使用的 `intent` 字段完全一致。从映射表取键是唯一能保证不漂移的写法——
手抄一份 5 元素枚举，迟早会与 `cypher_templates` 分叉。

**P1-1 与 P1-2 在依赖不可用时一律 503，不降级**（契约 §5-1）。理由不是「懒得降级」：
`/api/chat` 有向量路可退，所以它能降级；本端点只有图谱一路，没有备选数据源，
「降级」在语义上就不成立。更关键的是，若返回 `200 + items: []`，调用方无法区分
「该英雄确实没有克制关系」与「Neo4j 挂了」——这正是本项目一直在防的静默失败，
而项目二的审计状态机必须能区分业务失败与基础设施失败。

错误响应形状统一为 `{error, detail}`（见 `app/api/_contract.py`），由 `app/main.py`
注册的 `ContractError` 处理器落地。
"""
from __future__ import annotations

import math
from typing import Final

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api._contract import (
    ID_RE,
    bad,
    link_one_hero,
    not_found,
    server_error,
    unavailable,
    validate_int_range,
    validate_patches,
)
from app.api.docs import patch_hint
from app.config import settings
from app.retrieval import neo4j_client
from app.retrieval.cypher_templates import INTENT_TO_TEMPLATE

router = APIRouter(tags=["graph"])

# ---------------------------------------------------------------- 常量

# 5 个枚举 = 项目一公开的意图名（契约 §1 P1-1 表）。顺序即错误信息里的展示顺序。
RELATIONS: Final[tuple[str, ...]] = tuple(INTENT_TO_TEMPLATE)

RELATION_MIN_LIMIT: Final[int] = 1
RELATION_MAX_LIMIT: Final[int] = 50

# P1-3 允许写入的关系类型。**与 `scripts/init_graph.py` 的 HERO_REL_TYPES 同集合**，
# 但刻意不 import 它：`app/` 不应依赖 `scripts/`（脚本目录在 uvicorn 下不在 sys.path 上，
# 一 import 就会 ImportError）。故这里复述集合本身，并在 DECISIONS.md 登记该同步点。
# RECOMMENDS_ITEM / RECOMMENDS_INSCRIPTION 不开放：它们的 MERGE 键含 build_index / order，
# 单条 upsert 表达不了「第几套出装的第几件」，硬开放只会写出语义残缺的关系（契约 §3）。
UPSERT_TYPES: Final[tuple[str, ...]] = ("COUNTERS", "SYNERGIZES")

# 回读用的**出边**模板：COUNTERS 的出边是 COUNTERS_OF_HERO，SYNERGIZES 的是 SYNERGY_BY_HERO。
# 从 INTENT_TO_TEMPLATE 取，避免手抄模板名。
_OUT_TEMPLATE: Final[dict[str, str]] = {
    "COUNTERS": INTENT_TO_TEMPLATE["COUNTER_OF"],
    "SYNERGIZES": INTENT_TO_TEMPLATE["SYNERGY"],
}

# 回读窗口取接口上限 50，而不是默认的 GRAPH_TOP_K（10）：模板按 weight/名称排序，
# 默认窗口会把刚写入的低权重关系挤出结果集，于是**一次成功的写入被误判成 500**。
VERIFY_LIMIT: Final[int] = RELATION_MAX_LIMIT


# ---------------------------------------------------------------- P1-1 请求/响应


class GraphRelationsRequest(BaseModel):
    hero: str = Field(..., description="英雄名 / 别名 / ename，内部走 entity_linking 消歧")
    relation: str = Field(..., description=" / ".join(RELATIONS))
    limit: int | None = Field(None, description=f"{RELATION_MIN_LIMIT}~{RELATION_MAX_LIMIT}，默认 GRAPH_TOP_K")
    patches: list[str] | None = Field(None, description="版本窗口，默认 settings.PATCH_WINDOW")


@router.post("/graph/relations")
def graph_relations(req: GraphRelationsRequest) -> dict:
    """P1-1：按英雄 + relation 枚举查图谱关系，返回 `Evidence` 列表（不另造结构）。"""
    if req.relation not in INTENT_TO_TEMPLATE:
        raise bad(
            "relation_invalid",
            f"relation 必须是 {' / '.join(RELATIONS)} 之一，收到：{req.relation!r}",
        )
    limit = validate_int_range(req.limit, RELATION_MIN_LIMIT, RELATION_MAX_LIMIT, "limit")
    patches = validate_patches(req.patches)
    hero = link_one_hero(req.hero)

    # 只把**显式给了**的参数透传下去，其余交给 run_template 的 config 缺省
    # （不在这里复述 settings.GRAPH_TOP_K / PATCH_WINDOW，否则又是第二个口径）。
    kwargs: dict = {"hero_id": hero.canonical_id}
    if limit is not None:
        kwargs["limit"] = limit
    if patches is not None:
        kwargs["patches"] = patches

    try:
        items = neo4j_client.query_evidence(INTENT_TO_TEMPLATE[req.relation], **kwargs)
    except neo4j_client.GraphUnavailable as e:
        raise unavailable("graph_unavailable", f"Neo4j 不可用，图谱关系查询失败：{e}") from e

    return {
        "hero": {
            "id": hero.canonical_id,
            "name": hero.canonical_name,
            "matched_by": hero.method,
        },
        "relation": req.relation,
        "count": len(items),
        "items": [e.model_dump() for e in items],
    }


# ---------------------------------------------------------------- P1-3 请求/响应


class RelationUpsertRequest(BaseModel):
    from_id: str = Field(..., description="起点英雄 ename（数字字符串），必须已存在于图中")
    to_id: str = Field(..., description="终点英雄 ename（数字字符串），必须已存在于图中")
    type: str = Field(..., description=" / ".join(UPSERT_TYPES))
    patch: str = Field(..., description="必须落在 settings.PATCH_WINDOW 内")
    reason: str = Field(..., description="非空；空理由的关系对答案无价值")
    weight: float | None = Field(None, description="数值，默认 1.0")
    source: str = Field(..., description="必须 http:// 或 https:// 开头")


def _validate_type(value: str) -> str:
    if value not in UPSERT_TYPES:
        raise bad(
            "type_invalid",
            f"type 只能是 {' / '.join(UPSERT_TYPES)}；"
            f"RECOMMENDS_ITEM / RECOMMENDS_INSCRIPTION 本次不开放写入（其 MERGE 键含 "
            f"build_index / order，单条 upsert 表达不了）。收到：{value!r}",
        )
    return value


def _validate_patch(patch: str) -> str:
    """§5-3：patch 必须在窗口内，否则「写进去但永远查不出来」。

    所有图谱模板都带 `WHERE r.patch IN $patches`。窗口外的 patch 写入会成功、
    回读（用同一窗口）也会失败 —— 但若不做前置校验，调用方拿到的是一次
    「200 且看起来正常」的写入，而这条关系在**任何**查询里都不存在。
    """
    if patch not in settings.PATCH_WINDOW:
        raise bad(
            "patch_out_of_window",
            f"patch 必须落在当前版本窗口内（{patch_hint()}），收到：{patch!r}。"
            f"窗口外写入的关系即使成功，也会被所有模板的 r.patch IN $patches 过滤掉，永远查不出来。",
        )
    return patch


def _validate_reason(reason: str) -> str:
    if not reason.strip():
        raise bad("reason_empty", "reason 必填且不能为空白：空理由的关系对答案无价值（契约 §1 P1-3）")
    return reason


def _validate_weight(weight: float | None) -> float:
    """weight 缺省 1.0（与 `scripts/init_graph.py` 写入的权重口径一致）。"""
    if weight is None:
        return 1.0
    if not math.isfinite(weight) or weight < 0:
        raise bad("weight_invalid", f"weight 必须是 ≥ 0 的有限数值，收到：{weight!r}")
    return float(weight)


def _validate_source(source: str) -> str:
    if not source.startswith(("http://", "https://")):
        raise bad("source_invalid", "source 必填且必须是 http/https 开头的可追溯地址（与 /api/docs/upload 同口径）")
    return source


def _validate_id(value: str, field: str) -> str:
    if not ID_RE.match(value):
        raise bad("id_invalid", f'{field} 必须是图谱中的数字 ename（如 "193"），收到：{value!r}')
    return value


# ---------------------------------------------------------------- P1-3 写入协议


def _nodes_exist_cypher() -> str:
    return "MATCH (h:Hero) WHERE h.id IN $ids RETURN h.id AS id"


def _edge_exists_cypher(rel_type: str) -> str:
    # rel_type 已过 UPSERT_TYPES 白名单校验，故可拼进语句（与 init_graph.py 对
    # HERO_REL_TYPES 的做法一致）；用户提供的 id/patch 一律走 $param 绑定。
    return (
        "MATCH (a:Hero {id: $from_id})-[r:" + rel_type + " {patch: $patch}]->(b:Hero {id: $to_id}) "
        "RETURN count(r) AS c"
    )


def _upsert_cypher(rel_type: str) -> str:
    """落库语句：MERGE 键与 SET 字段**逐字对齐** `scripts/init_graph.py`（契约 §1 P1-3）。

    init_graph 版：
      UNWIND $rows AS row
      MATCH (a:Hero {id: row.a}), (b:Hero {id: row.b})
      MERGE (a)-[rel:TYPE {patch: row.patch}]->(b)
      SET rel.reason = row.reason, rel.weight = row.weight, rel.source = row.source

    唯一键 = 起点 + 关系类型 + 终点 + patch（规格书 1.10）。已存在则覆盖
    reason / weight / source —— 与批量导入走同一套语义，两条写入路径不会产出不同形状的关系。
    """
    return (
        "MATCH (a:Hero {id: $from_id}), (b:Hero {id: $to_id}) "
        "MERGE (a)-[rel:" + rel_type + " {patch: $patch}]->(b) "
        "SET rel.reason = $reason, rel.weight = $weight, rel.source = $source"
    )


def _require_nodes_exist(from_id: str, to_id: str) -> None:
    """§5-2：写前显式校验两个端点节点存在。

    不校验的后果不是报错而是**静默**：MERGE 之前的 `MATCH (a:Hero {id: ...})` 若匹配为空，
    整条语句一行都不会执行 —— Neo4j 既不报错也不抛异常，端点会返回 200 而数据根本没写进去。
    故这里先把缺失的 id 找出来，任一缺失即 404 并回显缺失清单。
    """
    ids = list(dict.fromkeys((from_id, to_id)))  # 去重且保序：两端相同时不该查两次、也不该重复回显
    found = {row["id"] for row in neo4j_client.run_cypher(_nodes_exist_cypher(), ids=ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise not_found(
            "node_not_found",
            f"节点不存在于图谱中，无法建立关系（缺失：{missing}）。"
            f"关系端点必须已入库，否则写入会静默丢失。",
            missing=missing,
        )


def _edge_exists(rel_type: str, from_id: str, to_id: str, patch: str) -> bool:
    rows = neo4j_client.run_cypher(
        _edge_exists_cypher(rel_type), from_id=from_id, to_id=to_id, patch=patch
    )
    return bool(rows and rows[0]["c"])


def _read_back(rel_type: str, from_id: str, to_id: str, patch: str) -> bool:
    """写入后用**对应的模板**回读一次，确认该关系确实可见（契约 §1 P1-3 的 `verified`）。

    必须走 `query_evidence`（模板注册表）而不是另写一句 Cypher：要证明的正是
    「这条关系在**用户查询所走的路径**上可见」，用别的语句回读等于自证清白。
    窗口用 `[patch]` 而非全窗口：查的是**这一条**是否可见。
    """
    rows = neo4j_client.query_evidence(
        _OUT_TEMPLATE[rel_type], hero_id=from_id, patches=[patch], limit=VERIFY_LIMIT
    )
    # 出边模板组装的 hero_ids = [起点, 终点]（见 neo4j_client._row_to_evidence），故终点在列表内即可判定
    return any(to_id in e.hero_ids for e in rows)


@router.put("/graph/relations")
def upsert_relation(req: RelationUpsertRequest) -> dict:
    """P1-3：单条关系 upsert（本项目唯一的高危端点）。

    ⚠️ 改的是**图谱事实来源** —— 所有依赖该关系的答案都会跟着变。项目二会把它标为
    dangerous 级（默认禁用 + 显式开启 + 二次确认）并由网关代理调用。本补丁按要求
    只做输入校验与写入协议，**不引入鉴权/限流/审计**（那是项目二网关的职责，
    在此实现等于让 Agent 绕过管控）。

    顺序即纪律，不可调换：
      1. 字段校验（400）—— 纯函数，先于任何 IO；
      2. 节点存在性校验（404）—— §5-2，必须**先于写入**；
      3. 存在性查询定 action（created / updated）—— 必须在写入前问，写完就问不出来了；
      4. MERGE upsert；
      5. 模板回读（verified）—— 回读不到即 500，绝不返回「200 且 verified=false」。
    """
    rel_type = _validate_type(req.type)
    _validate_patch(req.patch)
    _validate_reason(req.reason)
    weight = _validate_weight(req.weight)
    _validate_source(req.source)
    from_id = _validate_id(req.from_id, "from_id")
    to_id = _validate_id(req.to_id, "to_id")

    try:
        _require_nodes_exist(from_id, to_id)
        action = "updated" if _edge_exists(rel_type, from_id, to_id, req.patch) else "created"
        neo4j_client.run_cypher(
            _upsert_cypher(rel_type),
            from_id=from_id,
            to_id=to_id,
            patch=req.patch,
            reason=req.reason,
            weight=weight,
            source=req.source,
        )
        verified = _read_back(rel_type, from_id, to_id, req.patch)
    except neo4j_client.GraphUnavailable as e:
        raise unavailable("graph_unavailable", f"Neo4j 不可用，关系写入失败：{e}") from e

    if not verified:
        # 这条分支就是 §5-2 要防的东西：语句没报错、回读却看不见。
        # 报 500 而不是 200：调用方（以及项目二的审计层）必须知道「答应了却没做到」。
        raise server_error(
            "write_not_verified",
            f"写入未通过回读校验：{from_id} -[{rel_type} {{patch: {req.patch}}}]-> {to_id} "
            f"在模板 {_OUT_TEMPLATE[rel_type]} 的查询结果中不可见。",
        )

    return {
        "action": action,
        "key": {"from_id": from_id, "type": rel_type, "to_id": to_id, "patch": req.patch},
        "verified": True,
    }
