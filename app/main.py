"""FastAPI 应用入口（规格书附录 A：app/main.py）。

M0 阶段仅挂载 /api/health；chat / graph / docs 路由随对应里程碑引入。
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health

app = FastAPI(
    title="Honor GraphRAG QA Agent",
    description="王者荣耀 GraphRAG 问答 Agent（Neo4j 图谱 + Chroma 向量 + LangGraph 编排）",
    version="0.1.0",
)

app.include_router(health.router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {"name": "honor-graphrag", "doc": "/docs", "health": "/api/health"}
