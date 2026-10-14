"""节点 [0]：实体链接 + 指代消解规则 1（规格书 4.2 步骤 0 / 4.10）。

**实体链接不调大模型**（4.3 已裁定），本节点直接复用 `app.retrieval.entity_linking.link`，
不在此处重写一遍——重写会立刻产生「两份口径」，而口径漂移正是本项目反复踩的坑。

本节点只判定 **规则 1**（当前轮无实体 + 含指代词 → 继承上一轮实体）。
规则 2/3 放在意图节点，因为它们的门控条件「本轮意图是否被关键词判定」要到路由之后才存在，
判定逻辑集中在 `app/agent/coref.py`，两节点共用同一套指代词/阈值定义。
"""
from __future__ import annotations

import logging

from app.agent.coref import first_pronoun, inherit_entities
from app.agent.state import AgentState
from app.retrieval.entity_linking import link

logger = logging.getLogger(__name__)


def entity_linking_node(state: AgentState) -> dict:
    question = state.get("question", "")
    last_ids = state.get("last_entities") or []

    res = link(question)
    entities = list(res.entities)
    unrecognized = list(res.unrecognized)
    coref_resolved: str | None = None
    resolved_question = question

    # --- 规则 1（4.10）：当前轮无实体 + 问句含指代词 → 继承上一轮实体 ---
    if not entities and last_ids and first_pronoun(question):
        inherited, resolved = inherit_entities(question, last_ids)
        if inherited:
            entities = inherited
            # 继承必须显式记录（4.10 规则 3），否则指代错误与「知识库没数据」在用户看来一样
            coref_resolved = f"「{question}」→「{resolved}」（规则1·指代词继承）"
            resolved_question = resolved
            logger.info("指代消解：%s", coref_resolved)

    logger.info(
        "实体链接：entities=%s unrecognized=%s",
        [(e.canonical_name, e.method) for e in entities],
        unrecognized,
    )
    return {
        "entities": entities,
        "unrecognized": unrecognized,
        "coref_resolved": coref_resolved,
        "resolved_question": resolved_question,
    }
