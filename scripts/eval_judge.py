"""M6 判官（LLM-as-judge）—— 「答案有据率」与「guard 拦下的是真越界还是误报」共用同一份判据。

**为什么判据必须写死在一个地方**：8.2 的「答案有据率」与需求方第 3 项要求的「guard 误报率」
本质是同一个判断（答案是否超出了给定依据），如果两处各写一套 rubric，两个比例就不可比，
也没法互相印证。故收敛到本模块，两个脚本共用。

**判据（与 `app/llm/guard.py` 的模块头口径一致，不另立标准）**：
  - 答案只能使用【资料】中出现的事实、英雄名、装备名、数值；资料没写的就是「无据」。
  - 资料里对某条关系的**解释**（如「后羿怕高爆发法师」这类原因说明）**不得**被抬成
    一类英雄的**类别**来回答 —— 这正是 guard 的 G3 要拦的形态，判 `class_extrapolation`。
  - 凭空出现的英雄名判 `fabricated_entity`（guard 的 G2 目标形态）。
  - 其它无法溯源的事实判 `other_unsupported`。

**为什么用 LLM 判官而不是纯规则**：guard 是**规则**（正则 + 词典），若再用同一套规则去
判它准不准，就是自证。判官要独立于被测对象，且要能识别「换个说法但仍是越界」的形态。
代价是判官自身有噪声 —— 故报告里对**被拦下的每一条**都附原文，便于人工复核，
且明确标注「判官是 LLM，不是独立第三方」。

用法（被 import）：
    from eval_judge import judge_answer
"""
from __future__ import annotations

import json
import logging
import re

from app.config import settings
from app.llm.client import LLMGenerationError, LLMUnavailableError
from app.schemas.chat import Evidence

logger = logging.getLogger(__name__)

_VIOLATION_TYPES = ("none", "class_extrapolation", "fabricated_entity", "other_unsupported")

JUDGE_SYSTEM = (
    "你是严格的资料忠实度判官。给定【资料】与【答案】，判断答案是否**完全**能从资料推出。\n"
    "判据：\n"
    "1. 答案里的每个事实性陈述都必须能在【资料】中找到依据。\n"
    "2. 资料里对某条关系的**解释**（例如「后羿怕高爆发法师」这类**原因说明**）"
    "只是该条关系的说明，**不得**被当成一类英雄的**类别**来回答；"
    "若答案把这种解释抬成类别主张（如问「后羿怕什么」答「后羿怕高爆发法师」），"
    "violation_type 记 class_extrapolation。\n"
    "3. 答案里出现【资料】中不存在的英雄名/装备名/铭文名，violation_type 记 fabricated_entity。\n"
    "4. 其它无法溯源的事实，violation_type 记 other_unsupported。\n"
    "5. 完全忠实于资料时 violation_type 记 none、grounded 记 true。\n"
    "只输出 JSON，不要解释："
    '{"grounded": true|false, "violation_type": "<none|class_extrapolation|fabricated_entity|other_unsupported>", '
    '"unsupported": ["<无据片段>"], "reason": "<一句话>"}'
)


def _render(evidence: list[Evidence]) -> str:
    return "\n".join(f"- {e.content}" for e in evidence) or "（无）"


def judge_answer(client, question: str, evidence: list[Evidence], answer: str) -> dict:
    """判一条答案。返回 `{grounded, violation_type, unsupported, reason, judge_error}`。

    **调用失败不算「有据」也不算「无据」**：单列 `judge_error`，由统计方决定如何处置
    （本项目的口径是「判官失败即从分母剔除并计数」，不允许静默当成通过）。
    """
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content":
            f"【资料】\n{_render(evidence)}\n\n【答案】\n{answer}\n\n"
            f"（用户原问题：{question}）\n请判定并只输出 JSON。"},
    ]
    try:
        # 判官用**独立预算**（config.JUDGE_MAX_TOKENS）：实测 2048 会被思考吃光，
        # 长资料（铭文/出装）上判官返回空答案（finish_reason=length）→ 分母被迫缩小。
        res = client.chat(messages, max_tokens=settings.JUDGE_MAX_TOKENS)
    except (LLMUnavailableError, LLMGenerationError) as e:
        return {"grounded": None, "violation_type": "judge_error", "unsupported": [],
                "reason": f"{type(e).__name__}: {e}", "judge_error": str(e)}

    text = res.content.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"grounded": None, "violation_type": "judge_error", "unsupported": [],
                "reason": f"判官输出非 JSON：{text[:200]}", "judge_error": "non-json"}
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        return {"grounded": None, "violation_type": "judge_error", "unsupported": [],
                "reason": f"判官 JSON 解析失败：{e}", "judge_error": "bad-json"}

    vt = str(data.get("violation_type") or "none").strip()
    if vt not in _VIOLATION_TYPES:
        vt = "other_unsupported"
    return {
        "grounded": bool(data.get("grounded")),
        "violation_type": vt,
        "unsupported": data.get("unsupported") or [],
        "reason": str(data.get("reason") or "")[:200],
        "judge_error": None,
    }
