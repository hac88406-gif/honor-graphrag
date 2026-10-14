"""M3 集成测试 —— Neo4j 断开降级（规格书 4.8-5 / M3 验收）。

验收原文：模拟 Neo4j 断开时，系统降级为纯向量检索并**返回 200 而非 500**。

分两段断言，避免把「编排层降级」和「API 层不吐 500」混为一谈：
  1. 图级：`graph_query` 捕获 `GraphUnavailable` 后置 `degraded=True` / `graph_available=False`，
     不抛异常，且**真的补跑一次向量检索**、答案里带「图谱不可用」标注；
  2. API 级：`/api/chat/sync` 在同样条件下返回 200，`type` 取值合法。

用 monkeypatch 强制 `query_evidence` 抛 `GraphUnavailable` 来模拟断开 —— 比真去停 Neo4j
容器更可控、更可重复（4.8-5 要求的是「失败时降级」，不是「Neo4j 真的关掉」）。
"""
from __future__ import annotations

import httpx
import pytest

from app.agent import graph as graph_mod
from app.config import settings
from app.retrieval.neo4j_client import GraphUnavailable

DEGRADE_NOTE = "图谱不可用，以下依据来自攻略文本检索"


@pytest.fixture
def neo4j_down(monkeypatch):
    """把图谱查询强制打成「不可用」：异常类型与真实断开时一致（GraphUnavailable）。"""

    def _boom(*_args, **_kwargs):
        raise GraphUnavailable("simulated: Neo4j 断开")

    monkeypatch.setattr("app.agent.nodes.graph_query.query_evidence", _boom)


@pytest.fixture
async def client(checkpointer, monkeypatch):
    """ASGI 直连客户端，与测试同处**一个事件循环**。

    不用 starlette 的 `TestClient`：它在自己的线程与事件循环里跑应用，而 `AsyncSqliteSaver`
    的 aiosqlite 连接是绑定事件循环的，跨循环复用会抛
    `RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop`。

    这里把 `get_graph()` 依赖的 checkpointer 指向测试用的内存库，
    因此走的仍是**真实的** `run()` / `get_graph()` 路径，只是不落真实会话文件。
    """
    await graph_mod.reset_graph()

    async def _test_checkpointer():
        return checkpointer

    monkeypatch.setattr(graph_mod, "get_checkpointer", _test_checkpointer)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await graph_mod.reset_graph()


# ---------------------------------------------------------------- 图级


async def test_graph_only_intent_falls_back_to_vector(graph, ask, neo4j_down):
    """COUNTER_BY 属**图谱单路**意图（4.4 主路径列）。

    这类意图本来不排 `vector_search`，所以 Neo4j 一断就必须靠 `route_after_graph_query`
    补一次向量检索 —— 否则「降级为纯向量检索」只是把 `graph_evidence` 清空，
    用户会因为「图谱没了」被拒答，而 Chroma 里其实有相关攻略文本。
    """
    s = await ask("degrade-graph", "铠被谁克制")

    assert s["graph_available"] is False
    assert s["degraded"] is True
    assert s["degradation_note"] == DEGRADE_NOTE
    assert s["graph_evidence"] == []
    assert s["vector_evidence"], "降级必须真的执行向量检索（否则等于没降级）"
    assert s["response_type"] != "reject", "有向量依据就不该拒答"
    assert DEGRADE_NOTE in s["answer"], "4.8-5：降级必须在答案中标注「图谱不可用」"
    # 意图与实体链接不依赖 Neo4j，降级不得影响它们；话题类型仍按意图记，不因降级改变
    assert s["intent"] == "COUNTER_BY"
    assert [e.canonical_name for e in s["entities"]] == ["铠"]
    assert s["last_topic"] == "graph"


async def test_hybrid_intent_does_not_search_vector_twice(graph, ask, neo4j_down, monkeypatch):
    """混合意图的向量检索已在同一超步并行执行，降级兜底边不得让它再跑一次。"""
    from app.agent.nodes import vector_search as vector_mod

    real = vector_mod.hybrid_search
    calls: list[str] = []

    def _counting(question, **kwargs):
        calls.append(question)
        return real(question, **kwargs)

    monkeypatch.setattr(vector_mod, "hybrid_search", _counting)

    s = await ask("degrade-hybrid", "亚瑟怎么出装")

    assert s["intent"] == "ITEM_BUILD"
    assert s["degraded"] is True
    assert len(calls) == 1, f"向量检索应只执行一次，实际 {len(calls)} 次"


# ---------------------------------------------------------------- API 级


async def test_api_chat_sync_returns_200_when_neo4j_down(client, neo4j_down, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)

    resp = await client.post(
        "/api/chat/sync",
        json={"session_id": "api-degrade", "question": "铠被谁克制"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] in {"answer", "low_confidence", "reject", "clarify"}
    assert body["intent"] == "COUNTER_BY"
    assert [e["canonical_name"] for e in body["entities"]] == ["铠"]
    assert body["debug"]["degraded"] is True
    assert body["debug"]["graph_available"] is False
    assert body["debug"]["degradation_note"] == DEGRADE_NOTE
    assert DEGRADE_NOTE in body["answer"]


async def test_api_chat_sync_reject_path_is_offline(client):
    """越界问句全程不碰 Neo4j（intent_routing 直接分流到 reject），也必须 200。"""
    resp = await client.post(
        "/api/chat/sync",
        json={"session_id": "api-reject", "question": "今天天气怎么样"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "reject"
    assert body["intent"] == "OUT_OF_SCOPE"
    assert body["answer"], "拒答必须给出可替代的提问方向，不能空字符串"
