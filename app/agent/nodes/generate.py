"""节点 [5]：答案组装（规格书 4.2 步骤 5 / 4.9 生成阶段约束）。

**M3 阶段是确定性组装，不接大模型**：规格书把「生成节点 + prompt 集中维护」列在 M4 交付。
本节点只做一件事——把 `evidence` 逐条摘录成答案并组装 citation。

它**不会引入 evidence 之外的任何事实**（4.9 生成约束第一条），因此 M4 换成 LLM 时，
「答案中的英雄名必须能在 evidence 中找到」这条硬约束仍由同一份 evidence 保证，
不会因为换了生成器而失效。数值（技能伤害/CD）同理：evidence 里没有的数值不出现。
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.schemas.chat import Citation, Evidence

logger = logging.getLogger(__name__)


def _citation(index: int, e: Evidence) -> Citation:
    """Evidence -> Citation（规格书 5.1：label 是给用户看的一行来源说明）。"""
    label = e.content if e.kind == "graph" else f"攻略文本（{e.source}）"
    return Citation(
        index=index,
        kind=e.kind,
        label=label[:200],
        url=e.source_url,
        patch=e.patch,
    )


def generate_node(state: AgentState) -> dict:
    evidence = list(state.get("evidence") or [])
    response_type = state.get("response_type", "answer")
    graph_evidence = [e for e in evidence if e.kind == "graph"]
    vector_evidence = [e for e in evidence if e.kind == "vector"]

    lines: list[str] = []

    # 4.8-5：降级时必须在答案中标注「图谱不可用」
    if state.get("degraded"):
        lines.append(f"（{state.get('degradation_note') or '图谱不可用'}）")
    # 4.9 低置信：正常生成但开头标注「依据较少，仅供参考」
    if response_type == "low_confidence":
        lines.append("以下内容依据较少，仅供参考。")

    if graph_evidence:
        lines.append("【图谱依据】")
        lines.extend(f"- {e.content}" for e in graph_evidence[:10])
    if vector_evidence:
        lines.append("【攻略依据】")
        for e in vector_evidence[:3]:
            snippet = " ".join(e.content.split())
            lines.append(f"- {snippet[:120]}")

    if not graph_evidence and not vector_evidence:
        lines.append("知识库中没有找到与该问题直接相关的记录。")

    answer = "\n".join(lines)
    citations = [_citation(i, e) for i, e in enumerate(evidence, start=1)]

    logger.info("答案组装：response_type=%s 证据 %d 条 -> citation %d 条", response_type, len(evidence), len(citations))
    return {"answer": answer, "citations": citations, "response_type": response_type}
