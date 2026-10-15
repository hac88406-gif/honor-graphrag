"""节点 [5]：答案组装（规格书 4.2 步骤 5 / 4.9 生成阶段约束）。

两种生成方式，由 `settings.GENERATION_MODE` 决定（决策见 DECISIONS.md）：

  - `template`（默认，测试用）：**确定性证据组装** —— 逐条摘录 `evidence` 并组装 citation。
    它**不会引入 evidence 之外的任何事实**（4.9 生成约束第一条），因此离线、确定性、可复现。
  - `llm`（M4 交付）：云端生成（`app/llm`）+ **生成后校验**。
    失败（未配置 / 网络 / 空答案 / 被截断 / 校验不通过）一律**回落到确定性组装**，
    绝不把空答案或越界答案交给用户 —— 这是本项目一贯在堵的静默失败。

**4.9 生成约束的三道防线**在本文件合龙：
  1. prompt 集中（`app/llm/prompts.py`，只依据资料回答）；
  2. 生成后校验（`app/llm/guard.py`，拦截「把资料里的解释当类别」的越界归纳）；
  3. **确定性兜底**（本文件的 `_template_body`，构造上不可能引入 evidence 之外的事实）。

**多意图告知**（M3 审核·修改三）：`matched_intents` 命中多个时，答案里显式说明本次只回答了哪个意图、
其余可继续追问。此前只做到「留痕」，用户拿到半个答案却不知情 —— 仍是静默失败的一种形态。
**仍不做多意图合并**（需求方明确推迟到 M4/M6）。

**流式**：LLM 路径下，正文由本节点经 LangGraph 自定义流推送，但**必须在校验通过之后**才推
（截断/空答案在流末才可判定，先推再撤回等于把不可用文本给了用户）；思考分片只触发一次
`thinking` 事件（「正在思考」），**不得混入正文**。前缀行（降级标注/低置信提示/多意图告知）
在调用模型前先推，保证流式文本与 `state.answer` 一致。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.config import settings
from app.llm import LLMCallError, build_messages, check_answer, get_cloud_client
from app.schemas.chat import Citation, Evidence

logger = logging.getLogger(__name__)

# 意图 -> 面向用户的中文标签（多意图告知用）。键取自 4.4 的封闭枚举，不含自造意图。
INTENT_LABELS: dict[str, str] = {
    "COUNTER_BY": "被谁克制",
    "COUNTER_OF": "克制谁",
    "SYNERGY": "搭档搭配",
    "ITEM_BUILD": "出装",
    "INSCRIPTION": "铭文",
    "GAMEPLAY": "打法思路",
    "MATCHUP": "怎么打",
    "TIER_META": "版本强度",
    "ENTITY_UNKNOWN": "英雄识别",
    "OUT_OF_SCOPE": "越界问句",
}


# ---------------------------------------------------------------- 流式事件

def _stream_writer():
    """取 LangGraph 自定义流写入器；不在流式上下文中时返回 None。"""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001 - 非流式调用（如单测直接调节点）不应因此报错
        return None


def _emit(writer, event: str, data: dict) -> None:
    if writer is None:
        return
    try:
        writer({"event": event, "data": data})
    except Exception as e:  # noqa: BLE001 - 流式推送失败不能让整轮回答失败
        logger.warning("流式事件推送失败（%s）：%s", event, e)


# 每个 token 帧最多这么多字。5.3 的示例是「一帧一小段文本」，整段一次推出去不算流式。
_TOKEN_CHUNK = 8


def _emit_text(writer, text: str) -> None:
    """把**已校验通过**的正文按小块推给前端（M5「SSE 流式逐字显示」）。

    **为什么是「先校验、后分块」而不是「边生成边推」**：guard 的 G2（英雄名越界）要拿全篇
    英雄名去比对、G3 要按句子窗口判，都必须**完整正文**才判得准；若边收边推，未校验内容
    会先到达前端 —— 推出去就撤不回，等于把 guard 架空。故校验完再分块推：协议上仍是多帧
    流式（前端逐段 append），但交付给用户的每一个字都已通过校验。
    """
    for i in range(0, len(text), _TOKEN_CHUNK):
        _emit(writer, "token", {"text": text[i:i + _TOKEN_CHUNK]})


# ---------------------------------------------------------------- 前缀与兜底正文

def _multi_intent_note(state: AgentState) -> str | None:
    """多意图告知：命中多个意图时说明本次回答的是哪个（M3 审核·修改三）。"""
    matched = list(state.get("matched_intents") or [])
    chosen = state.get("intent") or ""
    others = [i for i in matched if i != chosen]
    if not chosen or not others:
        return None
    label = INTENT_LABELS.get(chosen, chosen)
    rest = "、".join(f"「{INTENT_LABELS.get(i, i)}」" for i in others)
    return f"（本次只回答了「{label}」；您还提到了{rest}，可以继续追问。）"


def _prefix_lines(state: AgentState, response_type: str) -> list[str]:
    lines: list[str] = []
    # 4.8-5：降级时必须在答案中标注「图谱不可用」
    if state.get("degraded"):
        lines.append(f"（{state.get('degradation_note') or '图谱不可用'}）")
    # 4.9 低置信：正常生成但开头标注「依据较少，仅供参考」
    if response_type == "low_confidence":
        lines.append("以下内容依据较少，仅供参考。")
    note = _multi_intent_note(state)
    if note:
        lines.append(note)
    return lines


def _template_body(state: AgentState, evidence: list[Evidence]) -> str:
    """确定性证据组装（M3 行为，也是 LLM 路径的兜底）。

    只逐条摘录 evidence，**不归纳、不改写、不补充**：构造上不可能引入 evidence 之外的事实。
    """
    graph_evidence = [e for e in evidence if e.kind == "graph"]
    vector_evidence = [e for e in evidence if e.kind == "vector"]

    lines: list[str] = []
    if graph_evidence:
        lines.append("【图谱依据】")
        lines.extend(f"- {e.content}" for e in graph_evidence[:10])
    if vector_evidence:
        lines.append("【攻略依据】")
        for e in vector_evidence[:3]:
            snippet = " ".join(e.content.split())
            lines.append(f"- {snippet[:120]}")
    if not graph_evidence and not vector_evidence:
        lines.append("知识库中没有找到与该问题直接相关的记录。")
    return "\n".join(lines)


# ---------------------------------------------------------------- LLM 生成

def _llm_body(state: AgentState, evidence: list[Evidence], writer) -> tuple[str | None, dict]:
    """云端生成 + 生成后校验。返回 `(正文, 调试信息)`；任何失败返回 `(None, info)`。"""
    info: dict = {"mode": "llm", "model": settings.CLOUD_CHAT_MODEL, "guard": None,
                  "guard_degraded": False}

    client = get_cloud_client()
    if client is None:
        info.update({"fallback": True, "error": "云端 LLM 未配置（缺 CLOUD_BASE_URL / CLOUD_API_KEY / CLOUD_CHAT_MODEL）"})
        return None, info

    question = state.get("resolved_question") or state.get("question", "")
    messages = build_messages(question, evidence)

    try:
        if writer is not None:
            # 流式：思考分片到达时推一次「正在思考」；正文在流末统一校验后才交给用户
            result = client.stream_chat(
                messages,
                on_reasoning=lambda: _emit(writer, "thinking", {"text": "正在思考"}),
            )
        else:
            result = client.chat(messages)
    except LLMCallError as e:
        info.update({"fallback": True, "error": f"{type(e).__name__}: {e}"})
        logger.warning("云端生成失败，回落确定性组装：%s", e)
        return None, info

    info.update({
        "finish_reason": result.finish_reason,
        "completion_tokens": result.completion_tokens,   # 含思考，成本统计口径
        "reasoning_tokens": result.reasoning_tokens,
        "reasoning_chars": len(result.reasoning),        # 思考**不进答案**，只留痕便于排查
        "content_chars": len(result.content),
    })

    text = result.content.strip()
    if settings.GUARD_ENABLED:
        g = check_answer(text, evidence, question)
        info["guard"] = {"ok": g.ok, "reason": g.reason, "detail": g.detail, "degraded": g.degraded}
        # G2 词典不可用属 fail-open，但降级必须可见（只写日志等于静默消失）——见 DECISIONS 2026-10-15
        info["guard_degraded"] = g.degraded
        if not g.ok:
            info.update({"fallback": True, "error": f"生成后校验不通过（{g.reason}）：{g.detail}"})
            logger.warning("生成后校验不通过，回落确定性组装：%s / %s", g.reason, g.detail)
            return None, info

    info["fallback"] = False
    return text, info


# ---------------------------------------------------------------- 节点

def generate_node(state: AgentState) -> dict:
    evidence = list(state.get("evidence") or [])
    response_type = state.get("response_type", "answer")
    writer = _stream_writer()
    prefix = _prefix_lines(state, response_type)

    info: dict = {"mode": settings.GENERATION_MODE, "fallback": False, "guard_degraded": False}
    body: str | None = None

    if settings.GENERATION_MODE == "llm" and evidence:
        # 前缀行先推：它们属于答案的一部分，必须在正文之前到达前端
        for line in prefix:
            _emit(writer, "token", {"text": line + "\n"})
        body, info = _llm_body(state, evidence, writer)
        info["streamed"] = writer is not None
        if body is not None:
            # 校验通过才推正文（空答案/截断不得先推后撤），按小块推以便前端逐段显示
            _emit_text(writer, body)

    if body is None:
        body = _template_body(state, evidence)
        if settings.GENERATION_MODE == "llm":
            # 走到这里说明没拿到可用的模型正文（失败回落，或压根没有证据可喂给模型）。
            # 必须**赋值**而非 setdefault：初始 info 的 fallback 是 False，
            # setdefault 不会覆盖它，会把「没打云端」误报成「生成成功」。
            info["fallback"] = True
            info.setdefault("error", "无可用的模型正文，使用确定性证据组装")

    answer = "\n".join(prefix + [body])
    citations = [_citation(i, e) for i, e in enumerate(evidence, start=1)]

    logger.info(
        "答案组装：mode=%s response_type=%s 证据 %d 条 fallback=%s -> citation %d 条",
        info.get("mode"), response_type, len(evidence), info.get("fallback"), len(citations),
    )
    return {
        "answer": answer,
        "citations": citations,
        "response_type": response_type,
        "generation_info": info,
    }


def _citation(index: int, e: Evidence) -> Citation:
    """Evidence -> Citation（规格书 5.1：label 是给用户看的一行来源说明）。"""
    label = e.content if e.kind == "graph" else f"攻略文本（{e.source}）"
    return Citation(
        index=index,
        kind=e.kind,
        label=label[:200],
        url=e.source_url,
        patch=e.patch,
    )
