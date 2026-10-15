"""生成阶段 prompt 集中维护（规格书 4.9「prompt 集中维护」）。

**为什么单独一个模块**：4.9 的生成约束是「答案只能来自 evidence」这一硬约束的**第一道防线**。
散落在节点里会出现「改了一处、另一处还是旧 prompt」的不一致，而且 prompt 是评测时最常调的东西，
集中一处才能对照 M6 的失败样本批量迭代。

**这道防线的能力边界（实测）**：prompt **无法单独**阻止越界归纳 —— 需求方实测与
`scripts/compare_llm_models.py` 复跑都显示，资料写「妲己 克制 后羿：后羿怕高爆发法师」时，
`deepseek-chat` / `deepseek-v4-pro` / `deepseek-flash` 在**基础 prompt 与强化 prompt下均**
答成「后羿怕高爆发法师（比如妲己）」——把资料里的**解释**当成了**类别**。
故本模块的 `SYSTEM_GENERATE` 只负责「把约束讲清楚」，真正的拦截在 `app/llm/guard.py`。
"""
from __future__ import annotations

from app.schemas.chat import Evidence

# 生成系统提示。第 2 条是针对性加固：实测的越界归纳正是「把解释当类别」这一种形态。
SYSTEM_GENERATE = (
    "你是王者荣耀攻略助手。只能依据【资料】回答用户的问题。\n"
    "硬约束：\n"
    "1. 只能使用【资料】中出现的事实、英雄名、装备名、铭文名与数值；"
    "不得引入资料之外的信息，不得编造数值。\n"
    "2. 资料里对某条关系的**解释**（例如「后羿怕高爆发法师」这类**原因说明**）"
    "是对该条关系的说明，**不得**把它当成一类英雄的**类别**去回答，"
    "也不得据此推断资料未列出的其他英雄。\n"
    "3. 答案中的英雄名必须是【资料】里出现过的。\n"
    "4. 资料不足以回答时，直接说明「资料不足」，不要猜测。\n"
    "5. 用中文简洁作答，不要输出思考过程或推理步骤。"
)


def render_evidence(evidence: list[Evidence]) -> str:
    """把 evidence 渲染成【资料】块（图谱事实在前，文本片段在后）。

    渲染规则与 M3 的确定性组装保持一致口径：图谱证据是 `relation: content` 的原文事实，
    文本证据是 chunk 正文。**不做摘要、不做改写** —— 一旦在这里做二次加工，
    「答案只能来自 evidence」就变成了「答案来自我们对 evidence 的理解」。
    """
    lines: list[str] = []
    for e in evidence:
        if e.kind == "graph":
            lines.append(f"- {e.content}")
        else:
            lines.append(f"- {e.content.strip()}")
    return "\n".join(lines)


def build_messages(question: str, evidence: list[Evidence]) -> list[dict]:
    """构造 chat/completions 的 messages（system + user）。

    user 里把【资料】与【问题】分成两段，是为了让模型明确「哪些是给定事实、哪些是待答问题」；
    资料为空时显式写「（无）」，避免出现一个空的【资料】块让模型自行发挥。
    """
    rendered = render_evidence(evidence) or "（无）"
    user = f"【资料】\n{rendered}\n\n【问题】{question}\n请依据【资料】作答，不要展开资料之外的内容。"
    return [
        {"role": "system", "content": SYSTEM_GENERATE},
        {"role": "user", "content": user},
    ]
