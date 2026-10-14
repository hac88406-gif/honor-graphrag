"""节点 [3]：融合与去重（规格书 4.2 步骤 3）。

并行分支（graph_query / vector_search）在这里汇聚。LangGraph 的语义是：两个上游节点若在
同一超步被触发，本节点会等**两者都完成**后只执行一次——这正是 4.8-3「两路结果在融合节点汇聚」
所需的 join 行为，不需要手写同步原语。

版本过滤（4.2 步骤 3 的第一项）**不在这里做**：patch 窗口已由检索层统一下推到查询里
（图谱侧 `r.patch IN $patches`、向量侧 `where.patch $in`），避免同一次查询把旧版本数据取回来
再在内存里丢掉——那会白耗 IO，且一旦漏掉一处就变成静默的版本串味。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.schemas.chat import Evidence

logger = logging.getLogger(__name__)


def fuse_node(state: AgentState) -> dict:
    graph_evidence = list(state.get("graph_evidence") or [])
    vector_evidence = list(state.get("vector_evidence") or [])

    merged: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    # 图谱事实在前（确定性来源优先），向量证据按相关度序在后
    for e in graph_evidence + vector_evidence:
        key = (e.kind, e.content)
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)

    # 向量侧 top1 相似度是 4.9 三档判定的输入；BM25 字面命中没有相似度（score=None），
    # 此时 top_score 可能为 None —— 判定层必须区分「无相似度」与「相似度为 0」。
    scores = [e.score for e in vector_evidence if e.score is not None]
    top_score = max(scores) if scores else None

    logger.info(
        "融合：图谱 %d 条 + 向量 %d 条 -> 去重后 %d 条（top_score=%s）",
        len(graph_evidence), len(vector_evidence), len(merged), top_score,
    )
    return {"evidence": merged, "top_score": top_score}
