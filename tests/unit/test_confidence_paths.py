"""置信度判定单测（规格书 4.9 v1.5「按检索路径分别定义」）。

**这份测试存在的原因**：M3 的保守口径用「向量相似度」一把尺子量所有证据，
把 4 个图谱单路意图（COUNTER_BY/COUNTER_OF/SYNERGY/INSCRIPTION）在「无相似度可比」时
一律打成 `low_confidence` —— 把最可靠的官方 curated 关系贴上了最弱的标签。
4.9 v1.5 要求按路径选对应的依据维度，故逐路径写断言，防止口径回退。

覆盖四条路径 × 各自的档位边界：
  - 图谱单路：关系条数 1/2/≥3，**≥1 条即正常回答**；
  - 向量单路：top1 相似度三档 + 「BM25 无相似度」这一特殊档；
  - 混合路：双证取更保守者 / 仅单侧有据降级；
  - 无依据：拒答。
另外覆盖「图谱单路意图在 Neo4j 降级后走向量路」这一交叉情形。
"""
from __future__ import annotations

import pytest

from app.agent.nodes.confidence import confidence_node, graph_confidence
from app.config import settings
from app.schemas.chat import Evidence


def _graph(n: int) -> list[Evidence]:
    return [
        Evidence(kind="graph", content=f"英雄{i} 克制 铠：理由{i}", source="official",
                 relation="COUNTERS", patch="2026-10")
        for i in range(n)
    ]


def _vector(scores: list[float | None]) -> list[Evidence]:
    return [
        Evidence(kind="vector", content=f"攻略片段{i}", source="guide", patch="2026-10", score=s)
        for i, s in enumerate(scores)
    ]


def _state(evidence: list[Evidence], intent: str) -> dict:
    return {"evidence": evidence, "intent": intent}


# ---------------------------------------------------------------- 图谱单路

def test_graph_confidence_mapping():
    """关系条数 -> 置信度映射（阈值来自 config，M6 校准）。"""
    assert graph_confidence(1) == settings.CONF_GRAPH_1
    assert graph_confidence(2) == settings.CONF_GRAPH_2
    assert graph_confidence(3) == settings.CONF_GRAPH_3
    assert graph_confidence(9) == settings.CONF_GRAPH_3


@pytest.mark.parametrize(
    "n,expected_conf",
    [(1, settings.CONF_GRAPH_1), (2, settings.CONF_GRAPH_2), (3, settings.CONF_GRAPH_3)],
)
def test_graph_only_intent_answers_without_vector_evidence(n, expected_conf):
    """图谱单路：**≥1 条关系即正常回答**，绝不因为「没有文本相似度可比」降级。

    这是 M3 保守口径的反例回归 —— 那版实现会在 n=1 且无向量证据时返回 low_confidence。
    """
    out = confidence_node(_state(_graph(n), "COUNTER_BY"))
    assert out["response_type"] == "answer"
    assert out["confidence"] == pytest.approx(expected_conf)
    assert out["top_score"] is None


def test_graph_only_intent_two_relations_is_answer():
    out = confidence_node(_state(_graph(2), "INSCRIPTION"))
    assert out["response_type"] == "answer"


# ---------------------------------------------------------------- 混合路

def test_hybrid_intent_graph_only_is_downgraded():
    """混合路**仅图谱单侧有据** -> 降级（4.9 v1.5）。"""
    out = confidence_node(_state(_graph(2), "ITEM_BUILD"))
    assert out["response_type"] == "low_confidence"
    assert out["confidence"] == pytest.approx(settings.CONF_GRAPH_2)


def test_hybrid_intent_both_sides_takes_conservative_one():
    """混合路双证：取更保守者（min(图谱侧, 文本侧)）。"""
    out = confidence_node(_state(_graph(1) + _vector([0.91, 0.88]), "ITEM_BUILD"))
    assert out["response_type"] == "answer"
    assert out["confidence"] == pytest.approx(settings.CONF_GRAPH_1)
    assert out["top_score"] == pytest.approx(0.91)


def test_hybrid_intent_vector_side_below_high_is_downgraded():
    """文本侧相似度未达 CONF_HIGH（仅图谱侧够强）-> 降级。"""
    out = confidence_node(_state(_graph(2) + _vector([0.52]), "MATCHUP"))
    assert out["response_type"] == "low_confidence"


def test_hybrid_intent_vector_only_is_downgraded():
    """混合路只有文本侧有据 -> 降级（单侧有据即降级）。"""
    out = confidence_node(_state(_vector([0.9, 0.88]), "ITEM_BUILD"))
    assert out["response_type"] == "low_confidence"


# ---------------------------------------------------------------- 向量单路

def test_vector_only_high_with_two_evidence_is_answer():
    """4.9：相似度 ≥ CONF_HIGH **且** ≥2 条文本证据 -> 正常回答。"""
    out = confidence_node(_state(_vector([0.72, 0.68]), "GAMEPLAY"))
    assert out["response_type"] == "answer"
    assert out["confidence"] == pytest.approx(0.72)


def test_vector_only_single_evidence_high_is_downgraded():
    """单条文本证据不足以交叉印证 -> 降级（不是拒答）。"""
    out = confidence_node(_state(_vector([0.9]), "GAMEPLAY"))
    assert out["response_type"] == "low_confidence"


def test_vector_only_mid_similarity_is_downgraded():
    out = confidence_node(_state(_vector([0.5]), "TIER_META"))
    assert out["response_type"] == "low_confidence"


def test_vector_only_below_floor_is_reject():
    out = confidence_node(_state(_vector([0.3]), "GAMEPLAY"))
    assert out["response_type"] == "reject"


def test_bm25_without_score_is_downgraded_not_rejected():
    """BM25 字面命中没有相似度：不能断言「相似度 < 下限」而误判成「知识库没数据」。

    「检索到了但无相似度可比」与「没检索到」是两件事，前者必须降级回答而不是拒答。
    """
    out = confidence_node(_state(_vector([None]), "GAMEPLAY"))
    assert out["response_type"] == "low_confidence"
    assert out["confidence"] == pytest.approx(0.5)   # 中性展示值，不显示 0.00


# ---------------------------------------------------------------- 无依据 / 交叉情形

def test_no_evidence_is_reject():
    out = confidence_node(_state([], "COUNTER_BY"))
    assert out["response_type"] == "reject"
    assert out["confidence"] == 0.0


def test_degraded_graph_only_intent_falls_to_vector_path():
    """图谱单路意图在 Neo4j 降级后（4.8-5）证据全在文本侧 -> 判定自动走向量单路。

    不需要为降级再写一套阈值：证据构成变了，路径判定跟着变。
    """
    out = confidence_node(_state(_vector([0.8, 0.75]), "COUNTER_BY"))
    assert out["response_type"] == "answer"

    downgraded = confidence_node(_state(_vector([0.5]), "COUNTER_BY"))
    assert downgraded["response_type"] == "low_confidence"
