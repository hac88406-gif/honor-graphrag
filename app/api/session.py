"""DELETE /api/session/{session_id}：清空会话状态（规格书 5.2，M6 归属）。

**为什么 M6 才做这个端点**（5.2 表已标注）：M6 的多轮追问用例必须能在**同一 session_id**
上反复起新对话 —— 上一轮遗留的 `last_entities` / `last_intent` 会被下一轮指代消解继承，
不清会话就会把「铠被谁克制」的记忆带进下一条无关用例，导致跨用例串味、评测不可复现。

**清的是 checkpointer 里 thread_id = session_id 的全部 checkpoint**（4.8-4：thread_id 即会话标识），
用 `adelete_thread` 而非自建表：会话状态的权威存储就是 checkpointer，
另存一份等于制造第二个口径（本项目反复踩过的坑）。

**幂等**：删除不存在的 session 也返回 200 —— 「目标状态已达成」而非「操作失败」。
返回体带 `deleted` 供调用方确认，但**不返回「删了几条」**：那属于实现细节，
写进契约会让调用方对内部存储产生依赖。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.memory.checkpointer import get_checkpointer

router = APIRouter(tags=["session"])

logger = logging.getLogger(__name__)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    cp = await get_checkpointer()
    # 先 `setup()` 建表：LangGraph 的 checkpoint 表是**惰性创建**的（首次 aput 才建）。
    # 对一个「建库后还没聊过」的会话直接 DELETE，会因为表不存在抛
    # `sqlite3.OperationalError: no such table: checkpoints` —— 明明无事可删却报 500，
    # 与「幂等清空」的语义相悖。`setup()` 是 CREATE TABLE IF NOT EXISTS，重复调用无副作用。
    await cp.setup()
    await cp.adelete_thread(session_id)
    logger.info("会话已清空：session_id=%s", session_id)
    return {"session_id": session_id, "deleted": True}
