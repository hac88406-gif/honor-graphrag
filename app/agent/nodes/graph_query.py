"""节点 [2a]：Neo4j 图谱查询（规格书 4.2 步骤 2 / 4.7 模板 / 4.8-5 降级）。

**降级是本节点的核心职责**（4.8-5）：Neo4j 查询失败或超时时，不抛 500，
而是标记 `degraded=True` 并让下游用纯向量结果继续。这依赖检索层把 Neo4j 异常统一
收敛成 `GraphUnavailable`（9.1-3：外部调用必须有超时与异常处理）。

意图 → 模板的映射来自 `app.retrieval.cypher_templates.INTENT_TO_TEMPLATE`（M2 已固化），
本节点不重写映射。MATCHUP 不在该映射里（它是混合意图，4.4 的主路径列为「混合」），
这里显式补一条：用 `COUNTERS_BY_HERO` 查「谁克制敌方」——这正是「怎么打 Y」要的应对手段。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.retrieval.cypher_templates import INTENT_TO_TEMPLATE
from app.retrieval.neo4j_client import GraphUnavailable, query_evidence

logger = logging.getLogger(__name__)

# MATCHUP 的图谱侧取数口径：敌方英雄被谁克制（= 可选的应对英雄）。
MATCHUP_TEMPLATE = "COUNTERS_BY_HERO"

# 降级时写进答案的标注（4.8-5 要求「在答案中标注『图谱不可用』」）
DEGRADE_NOTE = "图谱不可用，以下依据来自攻略文本检索"


def _empty() -> dict:
    return {
        "graph_evidence": [],
        "graph_available": True,
        "degraded": False,
        "degradation_note": None,
    }


def graph_query_node(state: AgentState) -> dict:
    intent = state.get("intent", "")
    slots = state.get("slots") or {}

    if intent in INTENT_TO_TEMPLATE:
        template = INTENT_TO_TEMPLATE[intent]
        hero_id = slots.get("hero")
    elif intent == "MATCHUP":
        template = MATCHUP_TEMPLATE
        hero_id = slots.get("hero_enemy")
    else:
        # 本意图没有图谱侧（如 GAMEPLAY / TIER_META），空手返回，不算降级
        return _empty()

    if not hero_id:
        # 槽位缺失（如「怎么打」没给敌方）→ 无图谱可查；由澄清分支处理，不是降级
        logger.info("图谱查询跳过：意图 %s 缺少英雄槽位", intent)
        return _empty()

    try:
        evidence = query_evidence(template, hero_id=hero_id)
    except GraphUnavailable as e:
        # 4.8-5：不允许直接抛 500。降级为纯向量检索，并在答案中标注。
        logger.warning("Neo4j 不可用，降级为纯向量检索：%s", e)
        return {
            "graph_evidence": [],
            "graph_available": False,
            "degraded": True,
            "degradation_note": DEGRADE_NOTE,
        }

    logger.info("图谱查询：template=%s hero=%s 命中 %d 条", template, hero_id, len(evidence))
    return {
        "graph_evidence": evidence,
        "graph_available": True,
        "degraded": False,
        "degradation_note": None,
    }
