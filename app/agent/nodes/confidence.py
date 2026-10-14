"""节点 [4]：三档置信度判定（规格书 4.9）。

**判定必须是确定性规则，不得交给 LLM**（4.9 明确禁止）：
让模型自己判断该不该拒答，等于把最关键的安全机制交给最不稳定的组件。
阈值全部来自 `config`（4.9 实现约束：不得硬编码，M6 需校准）。

四档口径（4.9 表格，逐条对齐）：
  | 情形     | 判定条件                                          | 行为                    |
  | 实体未识别 | unrecognized 非空 且 无高置信候选                    | 澄清（由路由分支处理，不在本节点） |
  | 槽位不完整 | MATCHUP 缺我方英雄                                  | 澄清（同上）             |
  | 无依据   | 图谱返回空 **且** 向量 top1 < CONF_LOW(0.45)         | 拒答                    |
  | 低置信   | 相似度 0.45~0.60；**或** 图谱仅 1 条且无文本交叉印证   | 降级回答（加提示）        |
  | 有依据   | 相似度 ≥ 0.60 **且**（有图谱事实 **或** ≥2 条文本证据） | 正常回答                |

**边界处理**：BM25 字面命中没有相似度（`score=None`）。此时不能断言「相似度 < 0.45」，
否则会把「检索到了但无相似度可比」误判成「知识库没数据」——这是同一类静默失败的另一种形态。
故 `top is None` 且有文本命中时按低置信处理，绝不走拒答。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.config import settings

logger = logging.getLogger(__name__)


def confidence_node(state: AgentState) -> dict:
    evidence = list(state.get("evidence") or [])
    graph_n = sum(1 for e in evidence if e.kind == "graph")
    vector = [e for e in evidence if e.kind == "vector"]
    vector_n = len(vector)

    scores = [e.score for e in vector if e.score is not None]
    top = max(scores) if scores else None

    # 对外展示的 confidence：无相似度可比但确有文本命中时给中性值，避免显示 0.00 让人误读为「毫无依据」
    shown = float(top) if top is not None else (0.5 if vector_n else 0.0)

    # --- 无依据 -> 拒答（图谱空 且 向量空/相似度低于下限） ---
    if graph_n == 0 and vector_n == 0:
        logger.info("置信度判定：无依据（图谱 0 / 向量 0）-> 拒答")
        return {"response_type": "reject", "confidence": 0.0, "top_score": None}
    if graph_n == 0 and top is not None and top < settings.CONF_LOW:
        logger.info("置信度判定：无依据（top=%.3f < %.2f）-> 拒答", top, settings.CONF_LOW)
        return {"response_type": "reject", "confidence": float(top), "top_score": top}

    # --- 低置信 -> 降级回答 ---
    if (
        top is None                                   # 有文本命中但无相似度（BM25 字面命中）
        or top < settings.CONF_HIGH                   # 相似度落在 [LOW, HIGH)
        or (graph_n == 1 and vector_n == 0)           # 图谱仅 1 条且无文本证据交叉印证（4.9 口径调整）
    ):
        logger.info("置信度判定：低置信（图谱 %d / 向量 %d / top=%s）-> 降级回答", graph_n, vector_n, top)
        return {"response_type": "low_confidence", "confidence": shown, "top_score": top}

    # --- 有依据 -> 正常回答 ---
    if graph_n >= 1 or vector_n >= 2:
        logger.info("置信度判定：有依据（图谱 %d / 向量 %d / top=%.3f）-> 正常回答", graph_n, vector_n, top)
        return {"response_type": "answer", "confidence": shown, "top_score": top}

    # 兜底：相似度够高但证据条数不足以交叉印证（如仅 1 条文本且无图谱事实）-> 保守降级
    logger.info("置信度判定：证据不足交叉印证（图谱 %d / 向量 %d）-> 降级回答", graph_n, vector_n)
    return {"response_type": "low_confidence", "confidence": shown, "top_score": top}
