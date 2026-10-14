"""M3 集成测试的共享夹具。

`checkpointer` 用**内存** SQLite：每个测试拿到独立会话库，
既不污染真实会话库（data/checkpoints.sqlite），测试之间也不会互相串记忆。
`graph` 用同一份 checkpointer 编译编排图；`ask` 封装「按 session_id 跑一轮」，
thread_id = session_id（4.8-4）。
"""
from __future__ import annotations

import pytest

from app.agent.graph import build_graph
from app.memory.checkpointer import open_checkpointer


@pytest.fixture
async def checkpointer():
    async with open_checkpointer(":memory:") as cp:
        yield cp


@pytest.fixture
def graph(checkpointer):
    return build_graph(checkpointer)


@pytest.fixture
def ask(graph):
    async def _ask(session_id: str, question: str, **extra):
        return await graph.ainvoke(
            {"question": question, "session_id": session_id, **extra},
            {"configurable": {"thread_id": session_id}},
        )

    return _ask
