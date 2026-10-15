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


@pytest.fixture
def retrieval_stubbed(monkeypatch):
    """把图谱与向量检索换成可控输入（不依赖 Neo4j / Chroma，结果确定）。

    用于「检索两路皆空 -> 拒答」「答案只由 evidence 摘录而来」这类**编排级**断言：
    真实检索会引入数据依赖与不确定性，而这里要测的是编排与生成层的接线。
    """
    def _install(*, graph: list, vector: list):
        monkeypatch.setattr("app.agent.nodes.graph_query.query_evidence",
                            lambda template, **kw: list(graph))
        monkeypatch.setattr("app.agent.nodes.vector_search.hybrid_search",
                            lambda question, **kw: list(vector))
    return _install
