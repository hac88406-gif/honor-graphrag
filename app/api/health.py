"""/api/health：三项组件（neo4j / chroma / llm）真实状态探测。

规格书 5.2：GET /api/health 返回 {neo4j, chroma, llm} 三项状态。
M0 验收要求该项返回真实结果；每项附带 detail 便于排查（静默失败防御）。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


def _check_neo4j() -> dict:
    """探测 Neo4j 连通性：驱动级 verify_connectivity，失败不抛错只记录。"""
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
        )
        try:
            driver.verify_connectivity()
            return {"ok": True, "detail": f"connected: {settings.NEO4J_URI}"}
        finally:
            driver.close()
    except Exception as e:  # 连接失败/驱动缺失都归为不可用，并给出原因
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _check_chroma() -> dict:
    """探测 Chroma：嵌入式 PersistentClient 直接实例化 + heartbeat。"""
    try:
        import chromadb

        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        # heartbeat 返回当前毫秒时间戳，能返回即说明后端正常
        client.heartbeat()
        collections = client.list_collections()
        return {
            "ok": True,
            "detail": f"persistent@ {settings.CHROMA_PERSIST_DIR}, collections={len(collections)}",
        }
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _check_llm() -> dict:
    """探测 LLM 层：Ollama /api/tags（HTTP），并回显当前 LLM_MODE 与意图模型。"""
    try:
        resp = httpx.get(
            f"{settings.OLLAMA_BASE_URL}/api/tags",
            timeout=settings.NEO4J_CONNECT_TIMEOUT,
        )
        if resp.status_code != 200:
            return {"ok": False, "detail": f"ollama http {resp.status_code}"}
        models = [m.get("name") for m in resp.json().get("models", [])]
        return {
            "ok": True,
            "detail": (
                f"mode={settings.LLM_MODE}, intent_model={settings.INTENT_MODEL}, "
                f"ollama_models={models}"
            ),
        }
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


@router.get("/health")
def health() -> dict:
    return {
        "neo4j": _check_neo4j(),
        "chroma": _check_chroma(),
        "llm": _check_llm(),
    }
