"""节点 [6]：记忆写入（规格书 4.2 步骤 6 / 4.10）。

把本轮的 `last_entities / last_intent / last_topic` 写回 State，由 checkpointer
（thread_id = session_id）持久化，供**下一轮**的指代消解读取。这是 4.8-4
「SqliteSaver 替代手写 Redis」的落点。

**两条写入策略（避免把记忆写坏）**：
  1. 本轮没识别出实体时**不覆盖** `last_entities`——否则一句「怎么打」就会把上一轮的「铠」擦掉，
     下一轮追问再无实体可继承（这是「多轮记忆被自己清空」的典型静默失败）。
  2. 意图为 `ENTITY_UNKNOWN` / `OUT_OF_SCOPE` 时**不覆盖** `last_intent`——这两种取值不是
     用户的真实问题类型，写进去会让 4.10 规则 2 的意图继承继承到一个无意义的值。
"""
from __future__ import annotations

import logging

from app.agent.routing import topic_of
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

# 不写回 last_intent 的意图（它们不代表用户的真实问题类型）
_NON_TOPIC_INTENTS = ("ENTITY_UNKNOWN", "OUT_OF_SCOPE")


def memory_node(state: AgentState) -> dict:
    entities = list(state.get("entities") or [])
    intent = state.get("intent", "")
    topic = topic_of(intent)

    update: dict = {}
    ids = [e.canonical_id for e in entities if e.canonical_id]
    if ids:
        update["last_entities"] = ids
    if intent and intent not in _NON_TOPIC_INTENTS:
        update["last_intent"] = intent
    if topic != "none":
        update["last_topic"] = topic

    logger.info("记忆写入：%s", update)
    return update
