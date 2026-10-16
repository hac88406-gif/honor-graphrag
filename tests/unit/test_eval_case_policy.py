"""评测集准入规则门禁（缺陷 D1 的 L4 交付，2026-10-16）。

**规则原文**（需求方 2026-10-16 裁定）：
  任何新功能或新意图，评测集必须包含 ≥3 条「第一次使用者的原话」——
  不带方向词、不带术语、不照抄规格书例句；
  且**每条必须标注可追溯的真实来源（谁在何时打的）**，这批用例**不得由实现方自行编写**。

**为什么需要这条规则**（比 D1 的三层根因更值钱）：D1 缺陷（「镜的克制关系」被当成英雄未识别）
在意图路由 79 个用例、294 个测试**全绿**的情况下漏了过去——因为用例是照「设计过的问法」写的，
不是照「使用者第一次会怎么打」写的。L1/L2/L3 修的是这一次的洞，本规则防的是下一次同类的洞。

本文件把规则**机制化**（否则它只是一句口号）：
  1. 零提示类用例（`category: 零提示自然说法`）必须 ≥3 条；
  2. 每条必须带 `source` 字段，且来源里必须能看出「谁在何时」——含日期、且不得署名实现方；
  3. `expect_type: clarify` 的零提示用例，其 `expected_intent` 必须与规则路由结果一致
     （澄清路径在检索之前分流，**离线可判**，不需要服务与模型）。

**历史存量不追溯**：`freeform.yaml` 在 2026-10-16 之前的 74 条用例由实现方编写、未标注来源，
这是 D1 暴露出来的既成事实，如实记录在案，**不补造来源**（补造等于把这条规则本身变成摆设）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.retrieval.intent import route

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
ZERO_PROMPT_CATEGORY = "零提示自然说法"

# 来源必须含日期（谁在何时打的，缺「何时」就无法追溯）
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _load_all_cases() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for name in ("cases.yaml", "freeform.yaml"):
        data = yaml.safe_load((EVAL_DIR / name).read_text(encoding="utf-8"))
        out.extend((name, c) for c in data.get("cases") or [])
    return out


ZERO_PROMPT_CASES = [(f, c) for f, c in _load_all_cases() if c.get("category") == ZERO_PROMPT_CATEGORY]


def test_zero_prompt_class_exists_with_at_least_three_cases():
    """规则第 1 条：零提示自然说法类用例 ≥3 条。"""
    assert len(ZERO_PROMPT_CASES) >= 3, (
        f"零提示自然说法用例只有 {len(ZERO_PROMPT_CASES)} 条，少于准入规则要求的 3 条"
    )


def test_every_zero_prompt_case_has_traceable_source():
    """规则第 2 条：每条必须能追溯到「谁在何时打的」，且不得由实现方自行编写。"""
    problems: list[str] = []
    for fname, case in ZERO_PROMPT_CASES:
        src = (case.get("source") or "").strip()
        if not src:
            problems.append(f"{fname}:{case.get('id')} 缺少 source 字段（无法追溯来源）")
            continue
        if not _DATE_RE.search(src):
            problems.append(f"{fname}:{case.get('id')} 的 source 未标明日期：{src!r}")
        if "实现方" in src:
            problems.append(f"{fname}:{case.get('id')} 的 source 署名实现方，违反「不得自行编写」：{src!r}")
    assert not problems, "零提示用例的来源标注不合格：\n  " + "\n  ".join(problems)


def test_zero_prompt_cases_declare_intent_and_type():
    """规则第 2 条补充：标注必须完整（否则「零提示」只是一句问句，无法判定）。"""
    problems = [
        f"{fname}:{case.get('id')}"
        for fname, case in ZERO_PROMPT_CASES
        if not case.get("expected_intent") or not case.get("expect_type")
    ]
    assert not problems, "零提示用例缺少 expected_intent / expect_type：\n  " + "\n  ".join(problems)


@pytest.mark.parametrize(
    "fname,case", ZERO_PROMPT_CASES, ids=[c.get("id") for _f, c in ZERO_PROMPT_CASES]
)
def test_clarify_zero_prompt_case_is_offline_checkable(fname: str, case: dict) -> None:
    """规则第 3 条：`expect_type: clarify` 的零提示用例必须能**离线**核对（澄清先于检索分流）。"""
    if case.get("expect_type") != "clarify":
        pytest.skip("非澄清用例：其期望类型依赖检索结果，由在线评测核对")
    got = route(case["question"]).intent
    assert got == case["expected_intent"], (
        f"{fname}:{case['id']}「{case['question']}」期望 {case['expected_intent']}，实际 {got}"
    )
