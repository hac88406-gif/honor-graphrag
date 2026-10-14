"""/api/chat/sync：同步问答（规格书 5.2 / 5.1 ChatResponse 契约）。

M3 只落这一条最小骨架——5.2 明确「`/api/chat/sync` **必须存在**」，M6 的评测脚本依赖它
批量跑分（否则要解析 SSE，容易出错）。SSE 版 `POST /api/chat` 与
`/api/graph/import`、`/api/docs/upload`、`DELETE /api/session/{id}` 随 M4/M5 引入。

**为什么这里没有 try/except 兜底 Neo4j**（4.8-5 / M3 验收：模拟 Neo4j 断开必须返回 200 而非 500）：
降级是 `graph_query` 节点的职责，异常在编排层内部就被收敛成 `degraded=True`，
根本不会穿透到本层。若在此处再包一层「Neo4j 异常 -> 200」，就会把真正的编程错误
（如 State 字段拼错）一起吞掉 —— 那正是本项目一直在防的静默失败。
故本层只做 State -> ChatResponse 的映射，不吞异常。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.agent.graph import run
from app.config import settings
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


def _debug(state: dict) -> dict:
    """DEBUG=1 时的排查信息（5.1：`debug` 仅在 DEBUG=1 时返回）。

    把「中间结果」明写出来：意图命中留痕、降级标记、指代消解动作、槽位、证据计数。
    这些都是「错了也不报错」的环节，不给出来就只能靠猜。
    """
    return {
        "intent_method": state.get("intent_method"),
        "matched_intents": state.get("matched_intents") or [],
        "slots": state.get("slots") or {},
        "coref_resolved": state.get("coref_resolved"),
        "resolved_question": state.get("resolved_question"),
        "graph_available": state.get("graph_available"),
        "degraded": bool(state.get("degraded")),
        "degradation_note": state.get("degradation_note"),
        "top_score": state.get("top_score"),
        "evidence_count": len(state.get("evidence") or []),
        "error": state.get("error"),
    }


@router.post("/chat/sync", response_model=ChatResponse)
async def chat_sync(req: ChatRequest) -> ChatResponse:
    state = await run(req.question, req.session_id)
    return ChatResponse(
        session_id=req.session_id,
        type=state.get("response_type") or "reject",
        answer=state.get("answer") or "",
        citations=state.get("citations") or [],
        confidence=float(state.get("confidence") or 0.0),
        intent=state.get("intent") or "",
        entities=state.get("entities") or [],
        clarify_options=state.get("clarify_options") or [],
        debug=_debug(state) if settings.DEBUG else None,
    )
