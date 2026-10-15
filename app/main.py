"""FastAPI 应用入口（规格书附录 A：app/main.py）。

已挂载：`/api/health`（M0）、`/api/chat/sync`（M3 最小骨架，5.2 要求必须存在）、
`/api/chat`（M5 SSE 流式问答）。

**尚未挂载（5.2 表中其余三条）**：`POST /api/graph/import`、`POST /api/docs/upload`、
`DELETE /api/session/{session_id}` —— 它们不属于任何里程碑的交付/验收条目（M5 验收只含前端四项），
故未擅自实现，归属待需求方裁定（见 M5 报告 §4）。
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import chat, health

app = FastAPI(
    title="Honor GraphRAG QA Agent",
    description="王者荣耀 GraphRAG 问答 Agent（Neo4j 图谱 + Chroma 向量 + LangGraph 编排）",
    version="0.1.0",
)

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {"name": "honor-graphrag", "doc": "/docs", "health": "/api/health"}
