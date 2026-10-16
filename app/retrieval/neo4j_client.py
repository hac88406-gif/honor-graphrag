"""Neo4j 访问封装（规格书 4.5 / 9.1-3：外部调用必须有超时与异常处理）。

上层（M3 编排）只通过本模块跑模板；失败一律抛 `GraphUnavailable`，
由编排层降级为纯向量检索（M3 验收项：模拟 Neo4j 断开时返回 200 而非 500）。
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import settings
from app.retrieval import cypher_templates as ct
from app.schemas.chat import Evidence

logger = logging.getLogger(__name__)

# 模板名 -> 关系类型（Evidence.relation 字段取值）
TEMPLATE_RELATION = {
    "COUNTERS_BY_HERO": "COUNTERS",
    "COUNTERS_OF_HERO": "COUNTERS",
    "SYNERGY_BY_HERO": "SYNERGIZES",
    "ITEMS_BY_HERO": "RECOMMENDS_ITEM",
    "INSCRIPTIONS_BY_HERO": "RECOMMENDS_INSCRIPTION",
}


class GraphUnavailable(RuntimeError):
    """Neo4j 不可达或查询失败。"""


@lru_cache(maxsize=1)
def _driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
    )


def reset_driver() -> None:
    """丢弃缓存的 driver（测试或连接参数变更后调用）。"""
    _driver.cache_clear()


def health() -> bool:
    try:
        _driver().verify_connectivity()
        return True
    except Exception as e:  # noqa: BLE001 - 健康检查吞掉所有异常，只回报可达性
        logger.warning("Neo4j 不可达：%s", e)
        return False


def run_template(template: str, **params) -> list[dict]:
    """执行参数化模板。patches/limit 缺省时取 config（9.1-2：不硬编码）。

    首个形参命名为 template（而非 name），以免与 HERO_BY_NAME 模板的 `$name` 参数冲突。
    """
    params.setdefault("patches", list(settings.PATCH_WINDOW))
    params.setdefault("limit", settings.GRAPH_TOP_K)
    cypher = ct.render(template)
    try:
        with _driver().session() as session:
            return [dict(rec) for rec in session.run(cypher, **params)]
    except Exception as e:
        raise GraphUnavailable(f"Neo4j 查询失败（{template}）：{e}") from e


# ---------------------------------------------------------------- 行 -> Evidence


def _row_to_evidence(template_name: str, row: dict) -> Evidence:
    relation = TEMPLATE_RELATION[template_name]
    source_url = row.get("source")
    patch = row.get("patch")
    kind = "graph"

    if template_name == "COUNTERS_BY_HERO":
        content = f"{row['counter_name']} 克制 {row['target_name']}：{row.get('reason') or '（官方未附理由）'}"
        hero_ids = [row["counter_id"], row["target_id"]]
    elif template_name == "COUNTERS_OF_HERO":
        content = f"{row['subject_name']} 克制 {row['target_name']}：{row.get('reason') or '（官方未附理由）'}"
        hero_ids = [row["subject_id"], row["target_id"]]
    elif template_name == "SYNERGY_BY_HERO":
        content = f"{row['subject_name']} 与 {row['target_name']} 是官方推荐搭档：{row.get('reason') or '（官方未附理由）'}"
        hero_ids = [row["subject_id"], row["target_id"]]
    elif template_name == "ITEMS_BY_HERO":
        content = f"{row['hero_name']} 第{int(row['build_index']) + 1}套出装 · 第{row['order']}件：{row['item_name']}"
        hero_ids = [row["hero_id"]]
    else:  # INSCRIPTIONS_BY_HERO
        content = (
            f"{row['hero_name']} 第{int(row['build_index']) + 1}套铭文 · {row['color']}：{row['inscription_name']}"
        )
        hero_ids = [row["hero_id"]]

    return Evidence(
        kind=kind,
        content=content,
        hero_ids=hero_ids,
        relation=relation,
        patch=patch,
        source="official",
        source_url=source_url,
        score=None,   # 图谱事实无相似度（5.1：score 仅向量侧使用）
    )


def rows_to_evidence(template_name: str, rows: list[dict]) -> list[Evidence]:
    return [_row_to_evidence(template_name, r) for r in rows]


def query_evidence(template: str, **params) -> list[Evidence]:
    """模板查询并直接返回 Evidence 列表（M3 的 graph_query 节点调用入口）。"""
    return rows_to_evidence(template, run_template(template, **params))


def run_cypher(cypher: str, **params) -> list[dict]:
    """原语级语句执行（补丁 P1 的图谱写入侧唯一入口）。

    **为什么必须开这个口子**：模板注册表（`cypher_templates.TEMPLATES`）覆盖的是**读语义**，
    而 P1 契约明确禁止新增模板；于是 P1-3 的「写前查节点是否存在」与「MERGE 单条 upsert」
    两句话在注册表里**无处安放**。若让端点在 `app/api/graph.py` 里自己拿 `_driver()`，
    「驱动获取」与「异常 -> GraphUnavailable」这两件事就被抄成了第二份 ——
    这正是本项目反复踩的「同一件事两个口径」。

    **纪律（与 9.1-4 一致）**：语句必须是**常量字符串 + `$param` 绑定**，禁止拼接用户输入
    （关系类型是封闭白名单，需拼进语句时先校验枚举，照 `scripts/init_graph.py` 的做法）。
    **回答用户问题的读路径仍必须走 `run_template` / `query_evidence`**；本函数只服务 P1-3 的
    写协议（写前节点存在性校验 + 单条 upsert），不得用来绕开模板注册表做检索。
    """
    try:
        with _driver().session() as session:
            return [dict(rec) for rec in session.run(cypher, **params)]
    except Exception as e:
        raise GraphUnavailable(f"Neo4j 语句执行失败：{e}") from e

