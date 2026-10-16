"""FastAPI 应用入口（规格书附录 A：app/main.py）。

已挂载：`/api/health`（M0）、`/api/chat/sync`（M3 最小骨架，5.2 要求必须存在）、
`/api/chat`（M5 SSE 流式问答）、`DELETE /api/session/{session_id}`（M6，评测多轮追问需清会话）、
`POST /api/docs/upload`（M7，上传语料入库）、
`POST /api/graph/relations` + `POST /api/retrieval/search` + `PUT /api/graph/relations`（补丁 P1）。

**5.2 表已全部落地**：`POST /api/graph/import` 的完整版仍不提供（规格书 5.2 定为 v1 不实现；
幂等导入已由 scripts/init_graph.py + test_neo4j_import_idempotent 覆盖），补丁 P1 只以
**受限形式**补上其中的单条 upsert（`PUT /api/graph/relations`），见 README 与 DECISIONS.md。
"""
from __future__ import annotations

from fastapi import FastAPI, Request

from app.api import chat, docs, graph, health, retrieval, session
from app.api._contract import ContractError

app = FastAPI(
    title="Honor GraphRAG QA Agent",
    description="王者荣耀 GraphRAG 问答 Agent（Neo4j 图谱 + Chroma 向量 + LangGraph 编排）",
    version="1.0.0",
)

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(session.router, prefix="/api")
app.include_router(docs.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(retrieval.router, prefix="/api")


@app.exception_handler(ContractError)
async def _contract_error_handler(_request: Request, exc: ContractError):
    """补丁 P1 新端点的错误响应统一形状 `{error, detail}`（契约 §1 通用约定）。

    做成应用级处理器而不是每个端点 try/except：新端点有 3 个、校验点有 8 处，
    逐处包一层迟早会漏一处，而漏掉的那处会退化成 500 + 一段 Python 堆栈。
    **既有端点不受影响** —— 它们抛的是 HTTPException，不会走到这里。
    """
    return exc.response


@app.get("/")
def root() -> dict:
    return {"name": "honor-graphrag", "doc": "/docs", "health": "/api/health"}

