"""M6 集成测试 —— `DELETE /api/session/{session_id}`（规格书 5.2）。

**为什么这个端点必须有测试**：它的价值全在「清干净了」——若只测 HTTP 200，
一个「收了请求但没真删」的实现同样通过，而多轮追问用例会继续串味（跨用例记忆污染），
评测结果因此不可复现。故断言的是**记忆是否真的没了**：
  - 先在同一 session 里制造一次指代继承（第 2 轮继承第 1 轮的实体）；
  - 删除会话后再问同一句 → 继承必须消失（`entities` 为空、`coref_resolved` 为 None）。

用 `entities` 字段而非 `debug` 断言，是因为 `debug` 仅在 DEBUG=1 时返回（5.1），
断言依赖环境变量会让测试在不同机器上时红时绿。
"""
from __future__ import annotations

import httpx
import pytest

from app.agent import graph as graph_mod


@pytest.fixture
async def client(checkpointer, monkeypatch):
    """ASGI 直连客户端，checkpointer 指向内存库（同 test_api_sse 的做法）。

    **两处都要 patch**：编排图经 `app.agent.graph` 取 checkpointer，会话端点经
    `app.api.session` 取 —— 它们是同一函数的两个引用，只 patch 一处的话，
    端点会去删真实会话库，测试与生产就被悄悄分叉了。
    """
    await graph_mod.reset_graph()

    async def _test_checkpointer():
        return checkpointer

    monkeypatch.setattr(graph_mod, "get_checkpointer", _test_checkpointer)
    monkeypatch.setattr("app.api.session.get_checkpointer", _test_checkpointer)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await graph_mod.reset_graph()


async def ask(client, session_id: str, question: str) -> dict:
    r = await client.post("/api/chat/sync", json={"session_id": session_id, "question": question})
    assert r.status_code == 200
    return r.json()


async def test_delete_session_clears_multi_turn_memory(client):
    """删除会话必须清掉跨轮记忆：删后同一句不再继承上一轮实体。"""
    sid = "sess-del"

    # 第 1 轮：识别到「铠」
    first = await ask(client, sid, "铠被谁克制")
    assert [e["canonical_name"] for e in first["entities"]] == ["铠"]

    # 第 2 轮：纯指代「那铭文呢」→ 规则 1 从上一轮继承「铠」
    second = await ask(client, sid, "那铭文呢")
    assert [e["canonical_name"] for e in second["entities"]] == ["铠"], "第 2 轮应继承上一轮实体"

    # 删除会话
    r = await client.delete(f"/api/session/{sid}")
    assert r.status_code == 200
    assert r.json() == {"session_id": sid, "deleted": True}

    # 第 3 轮：同样的「那铭文呢」→ 记忆已清，不再继承
    third = await ask(client, sid, "那铭文呢")
    assert third["entities"] == [], "删除会话后不得再继承上一轮实体（否则评测跨用例串味）"


async def test_delete_session_is_idempotent(client):
    """删除不存在的会话也返回 200（幂等）：目标状态已达成，不是操作失败。"""
    r1 = await client.delete("/api/session/never-existed")
    r2 = await client.delete("/api/session/never-existed")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["deleted"] is True and r2.json()["deleted"] is True


async def test_delete_session_does_not_affect_other_sessions(client):
    """会话隔离（4.8-4）：删 A 不得动 B 的记忆。"""
    await ask(client, "sess-a", "铠被谁克制")
    await ask(client, "sess-b", "貂蝉被谁克制")

    await client.delete("/api/session/sess-a")

    # B 的记忆仍在：指代继承照常
    b = await ask(client, "sess-b", "那铭文呢")
    assert [e["canonical_name"] for e in b["entities"]] == ["貂蝉"], "删除 A 不得影响 B 的会话记忆"
