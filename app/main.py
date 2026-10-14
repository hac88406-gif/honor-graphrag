"""FastAPI 应用入口（规格书附录 A：app/main.py）。

已挂载：`/api/health`（M0）、`/api/chat/sync`（M3 最小骨架，5.2 要求必须存在）。
graph / docs 路由与 SSE 版 `/api/chat` 随 M4/M5 引入。
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
