"""FastAPI 应用入口（规格书附录 A：app/main.py）。

已挂载：`/api/health`（M0）、`/api/chat/sync`（M3 最小骨架，5.2 要求必须存在）、
`/api/chat`（M5 SSE 流式问答）、`DELETE /api/session/{session_id}`（M6，评测多轮追问需清会话）、
`POST /api/docs/upload`（M7，上传语料入库）。

**5.2 表已全部落地**：唯一未提供的是 `POST /api/graph/import`，规格书 5.2 定为
v1 不实现（幂等导入核心能力已由 scripts/init_graph.py + test_neo4j_import_idempotent
覆盖，HTTP 包装边际价值低），见 README「非目标」。
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import chat, docs, health, session

app = FastAPI(
    title="Honor GraphRAG QA Agent",
    description="王者荣耀 GraphRAG 问答 Agent（Neo4j 图谱 + Chroma 向量 + LangGraph 编排）",
    version="1.0.0",
)

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(session.router, prefix="/api")
app.include_router(docs.router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {"name": "honor-graphrag", "doc": "/docs", "health": "/api/health"}
