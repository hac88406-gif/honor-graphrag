"""补丁 P1 集成测试 —— 三个新端点 + 复位回基线（契约 §6-1）。

覆盖范围（逐条对应契约 §6-1 的「新增测试至少覆盖」）：

  P1-1  `POST /api/graph/relations`
    - 5 个 relation 枚举各一条，且各自路由到**正确的模板**（用 Evidence.relation 反查）；
    - `limit` 越界 → 400；`limit` 真的生效（默认窗口截断 vs 上限窗口不截断）；
    - 英雄无法消歧 → 404 + `candidates`（0 个与 >1 个两种成因各一条）；
    - **方向性**：`COUNTER_BY` / `COUNTER_OF` 各写一条断言（项目一最容易写错的地方，
      方向写反时查询会**返回结果而不是报错**）；
    - Neo4j 断开 → **503**（不是 200、不是 500）。
  P1-2  `POST /api/retrieval/search`
    - `top_k` 越界 → 400；`query` 空/超长 → 400；hero 无法消歧 → 404；
    - Chroma 不可用 → **503**；在线时真的返回攻略原文片段。
  P1-3  `PUT /api/graph/relations`
    - 新建 → `created` + `verified=true`；同键重写 → `updated` 且**不新增关系数**；
      并端到端回读确认覆盖真的落库；
    - 节点不存在 → 404（回显 `missing`）；`patch` 越窗 / `type` 非枚举 / `reason` 空 /
      `source` 非 http(s) / `weight` 非法 / id 非数字 → 400；
    - 写入后关系数确实 +1（否则「返回 200 但没写进去」会漏过）。
  复位
    - 写入 → `reset_graph.py` → 回到基线 341 / 3165 / 527；
    - 再跑 `scripts/verify_data_layer.py`（官方复跑校验脚本）退出码为 0。

**为什么写用例都带 `graph_restored` 夹具**：P1-3 改的是图谱事实来源，用例本身就会
污染数据层。该夹具在 teardown 里调 `scripts/reset_graph.py` 的 `reset_all()` 把图谱
复位回 `data/graph/*.json` 基线 —— 复用补丁 §4 要求的那个复位入口，不写第二套复位逻辑。

**为什么 503 用例用 monkeypatch 而不是真去停容器**：契约 §5-1 要验的是「依赖不可用时
返回 503」，不是「Neo4j 真的关掉」。monkeypatch 抛出的异常类型与真实断开时**完全一致**
（`GraphUnavailable` / `VectorStoreUnavailable`），可重复且不会让服务在测试中途掉线
（交付报告要求的「服务环境状态」因此始终是「全部在跑」）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.retrieval.chroma_client import VectorStoreUnavailable
from app.retrieval.cypher_templates import INTENT_TO_TEMPLATE
from app.retrieval.neo4j_client import TEMPLATE_RELATION, GraphUnavailable

PROJECT_ROOT = Path(__file__).resolve().parents[2]

HERO = "铠"
HERO_ID = "193"
# 数据快照口径（data/graph 已冻结）：铠 克制 后羿(169) 是**出边**；诸葛亮(190) 克制 铠 是**入边**。
# 两条边方向相反且名字不重叠，正好用来抓「方向写反」。
COUNTER_OF_TARGET = "169"
COUNTER_BY_SOURCE = "190"
# 基线中不存在的一条边（193 的出边为 151/582/536/137/524/518/549/583/558/112/169，无 130），
# 因此「新建」用例与「复位」用例可以放心使用它。
NEW_EDGE = {"from_id": HERO_ID, "to_id": "130", "type": "COUNTERS", "patch": "2026-10"}
NEW_EDGE_SOURCE = "https://pvp.qq.com/web201605/herodetail/193.shtml"
NEW_EDGE_REASON_V1 = "测试写入：铠一技能可探草丛先手，宫本武藏无位移难以拉开"
NEW_EDGE_REASON_V2 = "测试写入（覆盖）：铠先手压制，宫本武藏需等二技能冷却再反打"

VALID_PUT = {
    **NEW_EDGE,
    "reason": NEW_EDGE_REASON_V1,
    "weight": 1.0,
    "source": NEW_EDGE_SOURCE,
}

# 5 个 relation 枚举 -> 期望的 Evidence.relation（用 TEMPLATE_RELATION 反查，不手抄）
RELATION_CASES = [
    (intent, TEMPLATE_RELATION[INTENT_TO_TEMPLATE[intent]])
    for intent in INTENT_TO_TEMPLATE
]

_HAS_SNAPSHOT = any(
    p.is_dir() and not p.name.endswith(".cache") for p in (PROJECT_ROOT / "data" / "raw").glob("*")
)


# ---------------------------------------------------------------- 夹具


@pytest.fixture
async def client():
    """ASGI 直连客户端（同 test_docs_upload 的做法，不启真实端口）。"""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def graph_restored(require_neo4j):
    """P1-3 写用例的护栏：用例跑完后把图谱复位回 `data/graph/*.json` 基线。

    复用 `scripts/reset_graph.py` 的 `reset_all()`（补丁 §4 要求的复位入口）。
    先调 `require_neo4j()`：服务不可达时按 tests/conftest 的门禁 skip/fail，
    **先于任何写入**——否则 teardown 的复位会对着一个连不上的库跑。
    """
    require_neo4j()
    yield
    from reset_graph import reset_all

    reset_all()


# ---------------------------------------------------------------- 离线：请求体形状


async def test_missing_required_field_returns_422(client):
    """缺必填字段 = 请求体形状不合法 → 422（FastAPI 对 BaseModel 的标准行为）。"""
    r = await client.post("/api/graph/relations", json={"relation": "COUNTER_BY"})
    assert r.status_code == 422


async def test_relation_not_in_enum_returns_400(client):
    """relation 取值不合法 → 400（**不是** 422：形状对、取值错）。"""
    r = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": "MATCHUP"}
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "relation_invalid"
    assert "COUNTER_BY" in body["detail"], "错误信息应列出合法枚举，便于调用方自查"


@pytest.mark.parametrize("limit", [0, 51, -1])
async def test_limit_out_of_range_returns_400(client, limit):
    """limit 越界一律 400，**不做静默截断**（截断会让调用方以为参数生效了）。"""
    r = await client.post(
        "/api/graph/relations",
        json={"hero": HERO, "relation": "COUNTER_BY", "limit": limit},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "limit_out_of_range"


@pytest.mark.parametrize(
    "patches", [["2026/10"], [], ["2026-10-01"], ["2026-10", "v2026-09"], ["2026-10", ""]]
)
async def test_patches_format_invalid_returns_400(client, patches):
    """patches 形状对（是字符串数组）但取值错 → 400。"""
    r = await client.post(
        "/api/graph/relations",
        json={"hero": HERO, "relation": "COUNTER_BY", "patches": patches},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "patches_invalid"


async def test_patches_element_type_invalid_returns_422(client):
    """patches 元素不是字符串 = **形状**错 → 422（不是 400）。

    与上一条用例配对，把 422 / 400 的分工钉住：形状/类型错由 FastAPI 判 422，
    取值错由我们判 400。混成一档会让调用方分不清「我传错了类型」还是「我传错了值」。
    """
    r = await client.post(
        "/api/graph/relations",
        json={"hero": HERO, "relation": "COUNTER_BY", "patches": [123]},
    )
    assert r.status_code == 422


async def test_hero_not_found_returns_404_with_candidates(client):
    """英雄无法消歧 → 404 且带 `candidates`（0 个候选与 >1 个候选两种成因）。

    不给 `candidates` 的话调用方只能自己猜「是名字错了还是接口坏了」；
    「猜一个最像的」正是本项目在防的静默错误，故一律要求澄清。
    """
    # 成因一：一个英雄都没识别出来（含英雄名以外的普通词，且不触发模糊匹配）
    r0 = await client.post(
        "/api/graph/relations", json={"hero": "北京到上海多远", "relation": "COUNTER_BY"}
    )
    assert r0.status_code == 404
    assert r0.json()["error"] == "hero_not_found"
    assert r0.json()["candidates"] == []

    # 成因二：一句话里出现两个英雄，无法判定要查哪个
    r2 = await client.post(
        "/api/graph/relations", json={"hero": f"{HERO}和后羿", "relation": "COUNTER_BY"}
    )
    assert r2.status_code == 404
    assert len(r2.json()["candidates"]) == 2, "多候选必须如实回显，由调用方澄清"


async def test_graph_relations_returns_503_when_neo4j_down(client, monkeypatch):
    """§5-1：图谱单路端点不得降级 —— 依赖不可用必须 503，**不能是 200**。

    200 + items=[] 会让调用方无法区分「该英雄确实没有克制关系」与「Neo4j 挂了」，
    项目二的审计状态机也就分不出业务失败与基础设施失败。
    """
    def _boom(*_args, **_kwargs):
        raise GraphUnavailable("simulated: Neo4j 断开")

    monkeypatch.setattr("app.retrieval.neo4j_client.query_evidence", _boom)

    r = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_BY"}
    )
    assert r.status_code == 503, f"依赖不可用必须 503，实际 {r.status_code}"
    assert r.json()["error"] == "graph_unavailable"


# ---------------------------------------------------------------- 离线：P1-2


@pytest.mark.parametrize("query", ["", "   ", "x" * 501])
async def test_retrieval_query_invalid_returns_400(client, query):
    r = await client.post("/api/retrieval/search", json={"query": query})
    assert r.status_code == 400
    assert r.json()["error"] in ("query_empty", "query_too_long")


@pytest.mark.parametrize("top_k", [0, 21])
async def test_retrieval_top_k_out_of_range_returns_400(client, top_k):
    r = await client.post("/api/retrieval/search", json={"query": "铠怎么出装", "top_k": top_k})
    assert r.status_code == 400
    assert r.json()["error"] == "top_k_out_of_range"


async def test_retrieval_hero_not_found_returns_404(client):
    r = await client.post(
        "/api/retrieval/search", json={"query": "怎么出装", "hero": "北京到上海多远"}
    )
    assert r.status_code == 404
    assert r.json()["error"] == "hero_not_found"
    assert r.json()["candidates"] == []


async def test_retrieval_returns_503_when_chroma_down(client, monkeypatch):
    """§5-1：检索端点同样不得降级 —— Chroma 不可用必须 503。"""
    def _boom(*_args, **_kwargs):
        raise VectorStoreUnavailable("simulated: Chroma 不可用")

    monkeypatch.setattr("app.retrieval.bm25.hybrid_search", _boom)

    r = await client.post("/api/retrieval/search", json={"query": "铠怎么出装"})
    assert r.status_code == 503, f"依赖不可用必须 503，实际 {r.status_code}"
    assert r.json()["error"] == "vector_store_unavailable"


# ---------------------------------------------------------------- 离线：P1-3 字段校验


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_error", "why"),
    [
        ("type", "RECOMMENDS_ITEM", "type_invalid", "本次不开放 build_index/order 语义的写入"),
        ("type", "counters", "type_invalid", "枚举大小写敏感，写错会静默写成另一个类型"),
        ("patch", "2020-01", "patch_out_of_window", "窗口外的关系写进去也永远查不出来"),
        ("patch", "2026/10", "patch_out_of_window", "格式不符即不在窗口内"),
        ("reason", "   ", "reason_empty", "空理由的关系对答案无价值"),
        ("source", "ftp://pvp.qq.com/x", "source_invalid", "来源必须可点开核对"),
        ("source", "", "source_invalid", "空来源无法追溯"),
        ("weight", -1.0, "weight_invalid", "负权重会让排序语义失真"),
        ("from_id", "abc", "id_invalid", "ename 必须是数字字符串"),
        ("to_id", "193.0", "id_invalid", "ename 不含小数点"),
    ],
)
async def test_put_field_validation_returns_400(client, field, bad_value, expected_error, why):
    """P1-3 的字段校验全部是纯函数，先于任何 IO —— 因此这些用例不需要服务在线。"""
    r = await client.put("/api/graph/relations", json={**VALID_PUT, field: bad_value})
    assert r.status_code == 400, f"{field}={bad_value!r} 应 400（{why}），实际 {r.status_code}"
    assert r.json()["error"] == expected_error


async def test_put_patch_error_echoes_current_window(client):
    """§5-3：越窗错误必须回显当前窗口，省得调用方自己去翻 config（照 docs.py 的 patch_hint 写法）。"""
    r = await client.put("/api/graph/relations", json={**VALID_PUT, "patch": "2020-01"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    for patch in settings.PATCH_WINDOW:
        assert patch in detail, f"错误信息应回显当前窗口（缺 {patch}）：{detail}"


# ---------------------------------------------------------------- 在线：P1-1


@pytest.mark.parametrize(("relation", "expected_relation"), RELATION_CASES)
async def test_relation_enums_route_to_expected_template(
    client, require_neo4j, relation, expected_relation
):
    """5 个枚举各一条：必须返回真实 Evidence，且 relation 字段落在正确的模板上。

    用 `limit=50` 而不是默认 10：铠的出装有 12 条、克制关系有 11 条，默认窗口会截断，
    于是这条用例就变成「测默认值」而不是「测枚举路由」。
    """
    require_neo4j()

    r = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": relation, "limit": 50}
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["hero"]["id"] == HERO_ID
    assert body["hero"]["matched_by"] in ("exact", "alias")
    assert body["relation"] == relation
    assert body["count"] == len(body["items"]) > 0, f"{relation} 应返回非空结果"
    assert {it["relation"] for it in body["items"]} == {expected_relation}, (
        f"{relation} 未路由到期望的模板关系类型 {expected_relation}"
    )
    for it in body["items"]:
        assert it["kind"] == "graph"
        assert it["score"] is None, "图谱事实无相似度（5.1：score 仅向量侧使用）"
        assert it["source_url"], "每条关系都必须可追溯"
        assert it["patch"] in settings.PATCH_WINDOW


async def test_limit_is_honored_not_silently_truncated(client, require_neo4j):
    """limit 必须真的改变结果集：默认窗口应截断到 GRAPH_TOP_K，上限窗口不截断。"""
    require_neo4j()

    default = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_OF"}
    )
    capped = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_OF", "limit": 50}
    )
    n_default = default.json()["count"]
    n_capped = capped.json()["count"]

    assert n_default == settings.GRAPH_TOP_K, f"未显式给 limit 时应落到 GRAPH_TOP_K，实际 {n_default}"
    assert n_capped > n_default, "limit=50 应比默认窗口返回更多（铠的出边共 11 条）"


async def test_counter_direction_is_not_reversed(client, require_neo4j):
    """方向性断言（规格书 4.4 点名最容易写错处）：方向写反时查询会**返回结果而不是报错**。

    COUNTER_BY(X) = X 被谁克制（入边）；COUNTER_OF(X) = X 克制谁（出边）。
    取一条真实存在的出边（铠 -> 后羿）与一条真实存在的入边（诸葛亮 -> 铠），
    两条边方向相反、名字不重叠，故「查出来的是谁」能唯一确定方向是否正确。
    """
    require_neo4j()

    of_items = (
        await client.post(
            "/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_OF", "limit": 50}
        )
    ).json()["items"]
    by_items = (
        await client.post("/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_BY", "limit": 50})
    ).json()["items"]

    def _others(items: list[dict]) -> set[str]:
        """取每条关系里「除铠之外」的那一端 id。"""
        out: set[str] = set()
        for it in items:
            out.update(i for i in it["hero_ids"] if i != HERO_ID)
        return out

    of_others, by_others = _others(of_items), _others(by_items)

    assert COUNTER_OF_TARGET in of_others, "COUNTER_OF 应返回铠**克制**的对象（后羿 169）"
    assert COUNTER_BY_SOURCE not in of_others, (
        "COUNTER_OF 不得返回克制铠的对象（诸葛亮 190）—— 出现即说明出入边写反了"
    )
    assert COUNTER_BY_SOURCE in by_others, "COUNTER_BY 应返回**克制**铠的对象（诸葛亮 190）"
    assert COUNTER_OF_TARGET not in by_others, (
        "COUNTER_BY 不得返回铠克制的对象（后羿 169）—— 出现即说明出入边写反了"
    )


# ---------------------------------------------------------------- 在线：P1-2


async def test_retrieval_search_returns_guide_chunks(client, require_chroma):
    """在线路径：返回的是攻略**原文片段**（kind=vector），不是答案。"""
    require_chroma()

    r = await client.post(
        "/api/retrieval/search",
        json={"query": "铠怎么出装", "hero": HERO, "top_k": 5, "patches": ["2026-10"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["query"] == "铠怎么出装"
    assert body["hero"]["id"] == HERO_ID
    assert body["count"] == len(body["items"]) > 0, "铠在库内有 4 篇攻略，不应返回空"
    assert all(it["kind"] == "vector" for it in body["items"])
    assert all(it["content"].strip() for it in body["items"]), "返回的必须是原文片段，不能是空串"
    assert all(HERO_ID in it["hero_ids"] for it in body["items"]), "hero 过滤必须真的生效"


async def test_retrieval_without_hero_returns_200(client, require_chroma):
    """hero 可选：不给则不做元数据过滤（通用/版本类问句本就不属于单个英雄）。"""
    require_chroma()

    r = await client.post("/api/retrieval/search", json={"query": "当前版本怎么上分"})
    assert r.status_code == 200, r.text
    assert r.json()["hero"] is None


# ---------------------------------------------------------------- 在线：P1-3 写入


async def test_put_creates_then_updates_same_key_without_adding_edges(client, graph_restored):
    """新建 -> created；同键重写 -> updated 且**不新增关系数**；覆盖必须真的落库。

    最后一步用只读端点回读，而不是直接查库：要证明的正是「这条关系在**用户查询所走的
    路径**上可见」，直查库等于自证清白。
    """
    from reset_graph import graph_counts

    before = graph_counts()

    r1 = await client.put("/api/graph/relations", json=VALID_PUT)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["action"] == "created"
    assert body1["verified"] is True, "写入必须通过模板回读校验"
    assert body1["key"] == {
        "from_id": NEW_EDGE["from_id"],
        "type": NEW_EDGE["type"],
        "to_id": NEW_EDGE["to_id"],
        "patch": NEW_EDGE["patch"],
    }

    mid = graph_counts()
    assert mid["rels"]["COUNTERS"] == before["rels"]["COUNTERS"] + 1, (
        "返回 200 却查不到新增关系 = 静默失败（§5-2 的核心场景）"
    )

    r2 = await client.put(
        "/api/graph/relations", json={**VALID_PUT, "reason": NEW_EDGE_REASON_V2}
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["action"] == "updated", "唯一键已存在时必须报 updated，不能谎报 created"
    assert body2["verified"] is True

    after = graph_counts()
    assert after["rels"]["COUNTERS"] == mid["rels"]["COUNTERS"], "同键重写不得新增关系"
    assert after["total_rels"] == mid["total_rels"]

    # 端到端：覆盖后的理由真的在只读端点可见
    reread = await client.post(
        "/api/graph/relations", json={"hero": HERO, "relation": "COUNTER_OF", "limit": 50}
    )
    contents = [it["content"] for it in reread.json()["items"]]
    assert any("宫本武藏" in c and NEW_EDGE_REASON_V2 in c for c in contents), (
        "覆盖写入的理由必须真的落库，否则 updated 只是嘴上说说"
    )
    assert not any(NEW_EDGE_REASON_V1 in c for c in contents), "旧理由应被覆盖掉"


async def test_put_missing_node_returns_404_and_writes_nothing(client, graph_restored):
    """§5-2：节点不存在必须 404（回显缺失 id），且**确实没有写入**。

    这条用例针对的正是「MATCH 匹配为空 -> MERGE 一行不执行 -> 不报错」：
    若只在响应里报 404 而实际写了东西（不可能），或反之返回 200 而没写，都算失败。
    """
    from reset_graph import graph_counts

    before = graph_counts()

    r = await client.put("/api/graph/relations", json={**VALID_PUT, "from_id": "999999"})
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["error"] == "node_not_found"
    assert body["missing"] == ["999999"]

    assert graph_counts() == before, "节点缺失时不得发生任何写入"


# ---------------------------------------------------------------- 复位


async def test_write_then_reset_returns_to_baseline(client, graph_restored):
    """补丁 §4 的核心验收：写入 -> 复位 -> 回到基线 341 / 3165 / 527。

    没有这条，项目二每演示一次写入就污染项目一一次，而 `init_graph.py` 是纯 MERGE、
    修不回来（唯一键不同就永远匹配不到脏关系）。
    """
    from reset_graph import graph_counts, reset_all

    baseline = graph_counts()
    assert baseline["total_nodes"] == 341 and baseline["total_rels"] == 3165, (
        f"复位用例要求图谱处于基线状态，实际 {baseline['total_nodes']}/{baseline['total_rels']}"
    )

    r = await client.put("/api/graph/relations", json=VALID_PUT)
    assert r.status_code == 200 and r.json()["action"] == "created"

    dirty = graph_counts()
    assert dirty["total_rels"] == baseline["total_rels"] + 1, "写入应让关系总数 +1"

    reset_all()

    restored = graph_counts()
    assert restored == baseline, "复位必须把图谱还原到写入前的基线"
    assert restored["total_nodes"] == 341
    assert restored["total_rels"] == 3165
    assert restored["rels"]["COUNTERS"] == 527


@pytest.mark.skipif(not _HAS_SNAPSHOT, reason="缺少 data/raw 快照，verify_data_layer.py 无法运行")
async def test_reset_then_verify_data_layer_script_passes(client, graph_restored, require_chroma):
    """契约 §6-1 点名的验收序列：写入 -> reset_graph.py -> verify_data_layer.py 通过。

    这里真的起子进程跑官方校验脚本（而不是在测试里复述它的断言），
    这样「报告说复位干净了」与「官方脚本说复位干净了」是同一个证据来源。
    """
    require_chroma()

    from reset_graph import reset_all

    r = await client.put("/api/graph/relations", json=VALID_PUT)
    assert r.status_code == 200 and r.json()["action"] == "created"

    reset_all()

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "verify_data_layer.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"verify_data_layer.py 未通过：\n{proc.stdout}\n{proc.stderr}"
    assert "结论：PASS" in proc.stdout
