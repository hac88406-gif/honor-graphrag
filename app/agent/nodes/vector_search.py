"""节点 [2b]：Chroma 向量检索（规格书 4.2 步骤 2 / 4.6）。

调用 M2 的 `bm25.hybrid_search`（向量 + BM25 → RRF 融合），**不在编排层重写检索**。
hero 过滤取自槽位（4.6：专有名词密度高的中文文本上，元数据过滤比模型选择重要得多）：
  - 单英雄意图（COUNTER_BY/ITEM_BUILD/…）→ 用 `hero`；
  - MATCHUP → 用 `hero_enemy`（「怎么打东皇」要的是东皇那侧的攻略）；
  - TIER_META（无英雄槽位）→ 不加 hero 过滤，仅按 patch 窗口过滤。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.retrieval.bm25 import hybrid_search
from app.retrieval.chroma_client import VectorStoreUnavailable

logger = logging.getLogger(__name__)


def vector_search_node(state: AgentState) -> dict:
    # 消解后的问句用于检索（「那铭文呢」→「铠铭文呢」），带上了实体名，对 BM25 更友好
    question = state.get("resolved_question") or state.get("question", "")
    slots = state.get("slots") or {}
    hero_id = slots.get("hero") or slots.get("hero_enemy")

    try:
        evidence = hybrid_search(question, hero_id=hero_id)
    except VectorStoreUnavailable as e:
        # 向量库是嵌入式零外部依赖，正常不应失败；一旦失败也不能把异常穿透到 API 层
        logger.error("向量检索失败：%s", e)
        return {"vector_evidence": [], "error": f"向量检索失败：{e}"}

    logger.info("向量检索：hero_filter=%s 命中 %d 条", hero_id, len(evidence))
    return {"vector_evidence": evidence, "error": state.get("error")}
