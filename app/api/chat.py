"""/api/chat：SSE 流式问答；/api/chat/sync：同步问答（规格书 5.2 / 5.3 / 5.1 契约）。

M3 落了 `/api/chat/sync` 最小骨架（5.2 明确它必须存在，M6 评测脚本依赖它批量跑分）。
M5 补上 SSE 版 `POST /api/chat` —— 前端「过程展示 + 逐字显示」必须有它。

**为什么用 FastAPI 原生 StreamingResponse 而不是 sse-starlette**（M5 决策，见 DECISIONS）：
本项目的既定取向是「够用且可控、不引额外依赖」。SSE 帧（`event:` 行 + `data:` 行 + 空行）
就是三行字符串拼接，原生 `StreamingResponse` 足够；为它引一个包只为省这几行不划算。

**为什么这里没有 try/except 兜底 Neo4j**（4.8-5 / M3 验收：模拟 Neo4j 断开必须返回 200 而非 500）：
降级是 `graph_query` 节点的职责，异常在编排层内部就被收敛成 `degraded=True`，
根本不会穿透到本层。若在此处再包一层「Neo4j 异常 -> 200」，就会把真正的编程错误
（如 State 字段拼错）一起吞掉 —— 那正是本项目一直在防的静默失败。
故本层只做 State -> ChatResponse 的映射，不吞异常。

**SSE 路径唯一的 except 是「把异常转成 `event: error`」**：HTTP 头在流开始时就已发出，
流中途抛异常无法再改状态码；不转成 error 事件的话，前端只会看到连接莫名中断（静默失败）。
该分支用 `logger.exception` 打完整堆栈 —— 转成事件是为了让前端可见，不是为了把错误藏起来。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.graph import run, stream_events
from app.config import settings
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])

logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 关掉反代（Nginx 等）的响应缓冲：否则流会被攒起来一次性吐给前端，看起来像没流式
    "X-Accel-Buffering": "no",
}


# 证据在 debug 里的字段白名单（M6 新增，理由见 `_debug` 的说明）
_EVIDENCE_FIELDS = ("kind", "content", "relation", "score", "source", "patch", "hero_ids")


def _evidence_dump(state: dict) -> list[dict]:
    """融合后 evidence 的紧凑快照（M6 评测 Recall@5 需要，仅 DEBUG=1 返回）。

    为什么必须给到**原文**而不是只给条数：8.2 的 Recall@5 是「关键依据是否出现在 top-5」，
    而 `citations` 里向量侧的 label 只有「攻略文本（来源）」——不含 chunk 正文，
    光看 citations 根本算不出向量路的召回。给 content 才能让评测脚本按 evidence 顺序判定。
    """
    out: list[dict] = []
    for e in state.get("evidence") or []:
        d = e.model_dump() if hasattr(e, "model_dump") else dict(e)
        out.append({k: d.get(k) for k in _EVIDENCE_FIELDS})
    return out


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
        # 融合后 evidence 原文（M6 新增）：Recall@5 只能从 evidence 顺序判，见 `_evidence_dump`
        "evidence": _evidence_dump(state),
        "generation": state.get("generation_info") or {},
        # 生成后校验的 G2 因词典不可用而失效时为 True（fail-open，但必须可见）
        "guard_degraded": bool((state.get("generation_info") or {}).get("guard_degraded")),
        "error": state.get("error"),
    }


def _to_response(req: ChatRequest, state: dict) -> ChatResponse:
    """State -> ChatResponse（5.1 契约）。SSE 的非流式分支与 /chat/sync 共用。"""
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


def _sse(event: str, data: dict) -> str:
    """5.3 的一帧：`event: <名>` + `data: <json>` + 空行。

    `ensure_ascii=False` 保证中文在 data 里是原文（前端直接可读，不用再解 \\uXXXX）。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/sync", response_model=ChatResponse)
async def chat_sync(req: ChatRequest) -> ChatResponse:
    state = await run(req.question, req.session_id)
    return _to_response(req, state)


@router.post("/chat")
async def chat(req: ChatRequest):
    """SSE 流式问答（5.2 / 5.3）。事件：node_start / thinking / evidence / token / citation / done / error。"""
    if not req.stream:
        # 不是「静默忽略」这个字段：5.2 把 /api/chat 定义为 SSE 流式问答，
        # 显式 stream=False 时按同步返回完整 ChatResponse（与 /chat/sync 同构）。
        return _to_response(req, await run(req.question, req.session_id))

    async def gen():
        try:
            async for ev in stream_events(req.question, req.session_id):
                yield _sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001 - 流已开始，无法再改状态码，只能转成 error 事件
            logger.exception("SSE 流中断：%s", e)
            yield _sse("error", {"message": f"服务异常：{type(e).__name__}，请重试或换个问法。"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
