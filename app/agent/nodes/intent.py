"""节点 [1]：意图路由 + 槽位抽取 + 指代消解规则 2/3（规格书 4.2 步骤 1 / 4.4 / 4.10）。

意图路由默认走**确定性规则**（M2 审核裁定「规则优先」），本节点直接调用
`app.retrieval.intent.route_rules`，不在编排层重写关键词逻辑。

指代消解的规则 2/3 放在这里而不是实体节点，因为它们的门控条件是
「本轮意图是否被关键词判定」——该信息只有路由之后才存在。判定与实现细节见 `app/agent/coref.py`。
"""
from __future__ import annotations

import logging

from app.agent.coref import has_followup_marker, inherit_entities, is_short
from app.agent.state import AgentState
from app.retrieval.intent import need_clarify_for, route_rules, slots_for

logger = logging.getLogger(__name__)


def intent_node(state: AgentState) -> dict:
    question = state.get("question", "")
    entities = list(state.get("entities") or [])
    last_ids = state.get("last_entities") or []
    last_intent = state.get("last_intent") or ""
    # 保留实体节点已记录的继承动作，本节点只在其上追加
    coref_resolved = state.get("coref_resolved")
    resolved_question = state.get("resolved_question") or question

    routed = route_rules(question, entities)
    intent = routed.intent
    slots = routed.slots
    need_clarify = routed.need_clarify
    matched = routed.matched_intents

    # 两条继承规则都以「简短追问」为前置条件（4.10 规则 2 的「长度 < 8 字」）
    if is_short(question):
        if matched and not entities and last_ids:
            # --- 规则 3（省略主语）：意图已被关键词判定，但问句没有实体 ---
            # 例：「貂蝉怕什么」→「怎么打」。按规则 1/2 的字面条件都不成立，语义上必须继承。
            inherited, resolved = inherit_entities(question, last_ids)
            if inherited:
                entities = inherited
                slots = slots_for(intent, question, entities)
                need_clarify = need_clarify_for(intent, slots)
                resolved_question = resolved
                coref_resolved = f"「{question}」→「{resolved}」（规则3·省略主语继承实体）"
                logger.info("指代消解：%s", coref_resolved)
        elif not matched and has_followup_marker(question) and last_intent:
            # --- 规则 2（简短追问）：意图无法判定 -> 继承上一轮意图，只替换实体 ---
            if not entities and last_ids:
                inherited, resolved = inherit_entities(question, last_ids)
                if inherited:
                    entities = inherited
                    resolved_question = resolved
            intent = last_intent
            slots = slots_for(intent, question, entities)
            need_clarify = need_clarify_for(intent, slots)
            coref_resolved = f"「{question}」→「{resolved_question}」（规则2·继承意图 {last_intent}）"
            logger.info("指代消解：%s", coref_resolved)

    # 9.1-6：日志记录关键中间结果（意图 / 槽位 / 是否需要澄清 / 多意图留痕），便于排查静默失败
    logger.info(
        "意图路由：intent=%s slots=%s need_clarify=%s matched_intents=%s",
        intent, slots, need_clarify, matched,
    )
    return {
        "entities": entities,
        "intent": intent,
        "slots": slots,
        "need_clarify": need_clarify,
        "intent_method": routed.method,
        "matched_intents": matched,
        "coref_resolved": coref_resolved,
        "resolved_question": resolved_question,
    }
