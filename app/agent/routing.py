"""意图 → 检索分支 / 话题类型的映射（规格书 4.4 主路径列 / 4.8-2 条件边 / 4.8-3 并行分支）。

**为什么把这张表单独放**：它是「意图」与「图结构」之间的唯一接口。
条件边路由（4.8-2）、并行分支判定（4.8-3）、记忆里的 `last_topic`（4.10）
三处都依赖同一份映射；分散定义就会出现「路由走了图谱但 last_topic 记成 vector」这类
自相矛盾，且**不报错**。集中一处即消除该类不一致。

分组依据是 4.4 表格的「主路径」列：
  - 图谱：COUNTER_BY（反向边）、COUNTER_OF（正向边）、SYNERGY、INSCRIPTION
  - 文本：GAMEPLAY、TIER_META
  - 混合：ITEM_BUILD（图谱+文本）、MATCHUP（混合）
"""
from __future__ import annotations

GRAPH_INTENTS: tuple[str, ...] = ("COUNTER_BY", "COUNTER_OF", "SYNERGY", "INSCRIPTION")
VECTOR_INTENTS: tuple[str, ...] = ("GAMEPLAY", "TIER_META")
HYBRID_INTENTS: tuple[str, ...] = ("ITEM_BUILD", "MATCHUP")


def branches_for(intent: str) -> list[str]:
    """该意图需要执行的检索节点名。

    返回**列表**是刻意的：LangGraph 的条件边路径函数返回列表时会在同一超步内**并行**执行
    多个节点（4.8-3 要求混合类意图下图谱与向量并行）。返回单元素列表即退化为单路。
    """
    out: list[str] = []
    if intent in GRAPH_INTENTS or intent in HYBRID_INTENTS:
        out.append("graph_query")
    if intent in VECTOR_INTENTS or intent in HYBRID_INTENTS:
        out.append("vector_search")
    return out


def topic_of(intent: str) -> str:
    """话题类型（4.10 的 last_topic）：graph / vector / hybrid / none。"""
    if intent in HYBRID_INTENTS:
        return "hybrid"
    if intent in GRAPH_INTENTS:
        return "graph"
    if intent in VECTOR_INTENTS:
        return "vector"
    return "none"
