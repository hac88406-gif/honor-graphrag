"""Evidence -> Citation 的统一构造（规格书 5.1）。

**为什么单独放一个模块**：citation 有**两个真实的推送点**，且两处必须逐字一致 ——
  1. `app/agent/graph.py` 的 `stream_events`：在**生成之前**把 citation 推给前端
     （规格书 v1.6 §3.4：依据在检索阶段就已确定，不必等生成完成，先推依据以降低感知延迟）；
  2. `app/agent/nodes/generate.py`：把 citations 写进终态 State（`/api/chat/sync` 与 M6 评测要用）。

index 基准（1-based，与答案里的【1】【2】对齐）与 label 截断长度都算对外契约，
各写一份迟早会分叉，故收敛到一处。
"""
from __future__ import annotations

from app.schemas.chat import Citation, Evidence

# label 是给用户看的一行来源说明，不截断会把整段 evidence 原文塞进来源卡片标题。
LABEL_MAX = 200


def build_citations(evidence: list[Evidence]) -> list[Citation]:
    """按 evidence 顺序生成 1-based citation（前端按 index 配对展开原文）。"""
    return [_citation(i, e) for i, e in enumerate(evidence, start=1)]


def _citation(index: int, e: Evidence) -> Citation:
    label = e.content if e.kind == "graph" else f"攻略文本（{e.source}）"
    return Citation(
        index=index,
        kind=e.kind,
        label=label[:LABEL_MAX],
        url=e.source_url,
        patch=e.patch,
    )
