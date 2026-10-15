"""节点 [4]：三档置信度判定（规格书 4.9 v1.5「按检索路径分别定义」）。

**判定必须是确定性规则，不得交给 LLM**（4.9 明确禁止）：
让模型自己判断该不该拒答，等于把最关键的安全机制交给最不稳定的组件。
阈值全部来自 `config`（4.9 实现约束：不得硬编码，M6 需校准）。

**为什么按路径分别定义**（4.9 v1.5 的修正点）：M3 的保守口径用「向量相似度」这一把尺子
量所有证据，于是 `COUNTER_BY/COUNTER_OF/SYNERGY/INSCRIPTION` 这四个**图谱单路**意图
一旦没有向量相似度可比（`top_score is None`）就一律被打成 `low_confidence` ——
把最可靠的官方 curated 关系贴上了最弱的标签。核心原则：**缺失 ≠ 低质量**，
每一路都要用**它自己**的依据维度来判：

  | 路径            | 依据维度                          | 判定                                        |
  |-----------------|-----------------------------------|---------------------------------------------|
  | 图谱单路        | 关系条数（官方 curated，确定性）  | ≥3 → CONF_GRAPH_3 / 2 → CONF_GRAPH_2 / 1 → CONF_GRAPH_1，**≥1 条即正常回答** |
  | 向量单路        | top1 相似度                       | ≥CONF_HIGH 且 ≥2 条文本证据 → 正常；[LOW,HIGH) → 降级；<LOW → 拒答 |
  | 混合路（双证）  | 取**更保守者**（min）             | min ≥ CONF_HIGH → 正常，否则降级            |
  | 混合路（单证）  | ——                                | **仅单侧有据 → 降级**                        |

**边界处理一**：BM25 字面命中没有相似度（`score=None`）。此时不能断言「相似度 < 0.45」，
否则会把「检索到了但无相似度可比」误判成「知识库没数据」——这是同一类静默失败的另一种形态。
故 `top is None` 且有文本命中时按低置信处理，绝不走拒答。

**边界处理二**：图谱单路意图在 Neo4j 断开时（4.8-5）会补一次向量检索，此时证据全在文本侧，
判定自动落到「向量单路」那一行——不需要为降级再写一套阈值。
"""
from __future__ import annotations

import logging

from app.agent.routing import HYBRID_INTENTS
from app.agent.state import AgentState
from app.config import settings

logger = logging.getLogger(__name__)


def graph_confidence(n: int) -> float:
    """图谱侧置信度：按**关系条数**映射（4.9 v1.5；阈值在 config，M6 校准）。

    ≥1 条即「有据」：官方页面的克制/搭档关系是 curated 事实，条数越多互相印证的强度越高，
    但不该因为「没有文本相似度可比」而降级。
    """
    if n >= 3:
        return settings.CONF_GRAPH_3
    if n == 2:
        return settings.CONF_GRAPH_2
    return settings.CONF_GRAPH_1


def _vector_tier(vector_n: int, top: float | None) -> str:
    """文本侧档位：none / unknown（无相似度可比）/ low / high。"""
    if vector_n == 0:
        return "none"
    if top is None:
        # BM25 字面命中：有文本、无相似度 —— 既不能说「无依据」也不能说「高相似」
        return "unknown"
    if top >= settings.CONF_HIGH:
        return "high"
    if top >= settings.CONF_LOW:
        return "low"
    return "none"   # 相似度低于下限，等同于「没检索到可用文本」


def confidence_node(state: AgentState) -> dict:
    evidence = list(state.get("evidence") or [])
    graph_n = sum(1 for e in evidence if e.kind == "graph")
    vector = [e for e in evidence if e.kind == "vector"]
    vector_n = len(vector)
    intent = state.get("intent", "")

    scores = [e.score for e in vector if e.score is not None]
    top = max(scores) if scores else None

    # 对外展示的 confidence：无相似度可比但确有文本命中时给中性值，避免显示 0.00 让人误读为「毫无依据」
    shown = float(top) if top is not None else (0.5 if vector_n else 0.0)
    g_conf = graph_confidence(graph_n) if graph_n else 0.0
    tier = _vector_tier(vector_n, top)

    # ---------- 1. 无依据 -> 拒答 ----------
    if graph_n == 0 and tier == "none":
        logger.info("置信度判定：无依据（图谱 0 / 向量 %d / top=%s）-> 拒答", vector_n, top)
        return {"response_type": "reject", "confidence": 0.0, "top_score": top}

    # ---------- 2. 纯图谱路（无任何文本证据） ----------
    if graph_n >= 1 and vector_n == 0:
        if intent in HYBRID_INTENTS:
            # 混合意图只拿到图谱侧 -> 单侧有据 -> 降级（4.9 v1.5）
            logger.info("置信度判定：混合路单侧有据（图谱 %d / 向量 0）-> 降级回答", graph_n)
            return {"response_type": "low_confidence", "confidence": g_conf, "top_score": top}
        logger.info("置信度判定：图谱单路有据（关系 %d 条 -> %.2f）-> 正常回答", graph_n, g_conf)
        return {"response_type": "answer", "confidence": g_conf, "top_score": top}

    # ---------- 3. 纯文本路（图谱空；含图谱单路意图在 Neo4j 降级后补检索的情形） ----------
    if graph_n == 0:
        if intent in HYBRID_INTENTS:
            # 混合意图只拿到文本侧 -> 单侧有据 -> 降级（4.9 v1.5）。
            # 与上面的「图谱单侧有据」对称：混合路的完整性要求两侧都到位。
            logger.info("置信度判定：混合路仅文本侧有据（图谱 0 / 向量 %d / top=%s）-> 降级回答", vector_n, top)
            return {"response_type": "low_confidence", "confidence": shown, "top_score": top}
        if tier in ("unknown", "low"):
            logger.info("置信度判定：文本单路 %s（向量 %d / top=%s）-> 降级回答", tier, vector_n, top)
            return {"response_type": "low_confidence", "confidence": shown, "top_score": top}
        # tier == high：4.9 要求「相似度 ≥ CONF_HIGH **且**（有图谱事实 或 ≥2 条文本证据）」
        if vector_n >= 2:
            logger.info("置信度判定：文本单路有据（向量 %d / top=%.3f）-> 正常回答", vector_n, top)
            return {"response_type": "answer", "confidence": shown, "top_score": top}
        logger.info("置信度判定：单条文本证据不足以交叉印证（向量 %d）-> 降级回答", vector_n)
        return {"response_type": "low_confidence", "confidence": shown, "top_score": top}

    # ---------- 4. 两侧都有证据 -> 混合路取更保守者 ----------
    if tier == "high":
        conf = min(g_conf, float(top))
        if conf >= settings.CONF_HIGH:
            logger.info("置信度判定：混合路双证（图谱 %d / 向量 %d / top=%.3f）-> 正常回答", graph_n, vector_n, top)
            return {"response_type": "answer", "confidence": conf, "top_score": top}
        logger.info("置信度判定：混合路取更保守者 %.2f -> 降级回答", conf)
        return {"response_type": "low_confidence", "confidence": conf, "top_score": top}

    # 文本侧未达 high（unknown / low / none）-> 仅图谱单侧有据 -> 降级（4.9 v1.5）
    logger.info(
        "置信度判定：混合路仅图谱侧有据（图谱 %d / 向量 %d / tier=%s）-> 降级回答", graph_n, vector_n, tier
    )
    return {"response_type": "low_confidence", "confidence": g_conf, "top_score": top}
