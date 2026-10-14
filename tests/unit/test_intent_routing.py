"""意图路由规则路径测试（规格书 4.4 / 4.2 步骤 [1]）。

需求方 2026-10-15 M2 审核条件一：当前 86 个用例里没有一个测 `route_rules()`——
唯一的 `test_intent_to_template_is_closed` 只检查枚举映射闭包，不测路由逻辑。
「规则优先」决定的全部风险都在覆盖率上，故本文件是 M3 的第一项交付。

要求（逐条对应）：
  - 每个意图 ≥3 条**真实问法**（不是关键词本身）；
  - 重点覆盖易混对：COUNTER_BY/COUNTER_OF、GAMEPLAY/MATCHUP、ITEM_BUILD/INSCRIPTION、
    OUT_OF_SCOPE/ENTITY_UNKNOWN；
  - 跨意图误判风险「谁能针对铠」当前落 MATCHUP（因 _MATCHUP 含"针对"）——已裁定归 COUNTER_BY，
    见 `test_who_counters_kai_ruling`。

条件二：本文件同时给出规则路径的**初步准确率**（`test_accuracy_summary` 打印真实数字），
作为 M6「意图路由准确率 ≥85%」的前置信号。该数字是自建问句集上的测量值，非独立评测集（M6 另建）。
"""
from __future__ import annotations

import pytest

from app.retrieval.intent import INTENTS, route

# ---------------------------------------------------------------- 真实问句集
# (问句, 期望意图, 备注)。问句是**真实问法**，不是关键词本身。
CASES: list[tuple[str, str, str]] = [
    # --- COUNTER_BY：X 被谁克制（反向边） ---
    ("铠被谁克制", "COUNTER_BY", "最直白问法"),
    ("谁能打铠", "COUNTER_BY", "主语在前"),
    ("铠怕谁", "COUNTER_BY", "口语「怕」"),
    ("谁克制铠", "COUNTER_BY", "「谁克制X」"),
    ("铠被谁压制", "COUNTER_BY", "「压制」变体"),
    ("铠被什么英雄克制", "COUNTER_BY", "「被什么」变体"),
    ("谁能针对铠", "COUNTER_BY", "★裁定：语义是「谁克制铠」，非 MATCHUP"),
    # --- COUNTER_OF：X 克制谁（正向边） ---
    ("铠克制谁", "COUNTER_OF", "「X克制谁」"),
    ("铠能打谁", "COUNTER_OF", "与「谁能打铠」互为反向"),
    ("铠压制谁", "COUNTER_OF", "「压制」变体"),
    ("铠欺负谁", "COUNTER_OF", "口语「欺负」"),
    # --- SYNERGY ---
    ("铠的搭档是谁", "SYNERGY", "「搭档」"),
    ("谁和铠好配合", "SYNERGY", "「配合」"),
    ("铠适合和谁开黑", "SYNERGY", "「开黑」"),
    ("铠和谁搭配好", "SYNERGY", "「搭配」"),
    # --- ITEM_BUILD ---
    ("铠怎么出装", "ITEM_BUILD", "「出装」"),
    ("铠的出装推荐", "ITEM_BUILD", "「出装」名词化"),
    ("铠出什么装备", "ITEM_BUILD", "「装备」"),
    ("铠第一件出什么", "ITEM_BUILD", "「第一件」"),
    # --- INSCRIPTION ---
    ("铠的铭文怎么配", "INSCRIPTION", "「铭文」"),
    ("铠用什么铭文", "INSCRIPTION", "「铭文」疑问"),
    ("铠的符文推荐", "INSCRIPTION", "「符文」同义"),
    ("铠铭文搭配", "INSCRIPTION", "「铭文」+「搭配」（优先级高于 SYNERGY）"),
    # --- GAMEPLAY ---
    ("铠怎么玩", "GAMEPLAY", "「怎么玩」"),
    ("铠的打法思路", "GAMEPLAY", "「打法/思路」"),
    ("铠的连招技巧", "GAMEPLAY", "「连招/技巧」"),
    ("铠怎么上手", "GAMEPLAY", "「上手」"),
    # --- MATCHUP ---
    ("怎么打东皇太一", "MATCHUP", "「怎么打Y」"),
    ("我玩铠怎么打吕布", "MATCHUP", "我方+敌方"),
    ("怎么针对铠", "MATCHUP", "★与「谁能针对铠」对照：这里「针对」属 MATCHUP"),
    ("如何打貂蝉", "MATCHUP", "「如何打」"),
    # --- TIER_META ---
    ("这个版本谁强", "TIER_META", "「版本/谁强」"),
    ("当前版本铠强度如何", "TIER_META", "「版本/强度」"),
    ("铠这个版本值得练吗", "TIER_META", "「版本/值得练」"),
    ("现在谁值得练", "TIER_META", "「值得练」"),
    # --- ENTITY_UNKNOWN（澄清，不拒答） ---
    ("东皇太一", "ENTITY_UNKNOWN", "纯实体无意图 -> 澄清"),
    ("铠", "ENTITY_UNKNOWN", "单实体"),
    ("貂蝉", "ENTITY_UNKNOWN", "单实体"),
    ("问个不存在的英雄", "ENTITY_UNKNOWN", "有王者语境但无实体 -> 澄清（9.2-5 不得拒答）"),
    # --- OUT_OF_SCOPE（拒答） ---
    ("今天天气怎么样", "OUT_OF_SCOPE", "无关话题"),
    ("帮我写一首诗", "OUT_OF_SCOPE", "无关话题"),
    ("北京到上海多远", "OUT_OF_SCOPE", "无关话题"),
    ("1加1等于几", "OUT_OF_SCOPE", "无关话题"),
]


def _route(question: str) -> str:
    return route(question, use_llm=False).intent


@pytest.mark.parametrize("question,expected,note", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_route_rules_single_intent(question: str, expected: str, note: str) -> None:
    got = _route(question)
    assert got == expected, f"「{question}」期望 {expected}（{note}），实际 {got}"


def test_dataset_covers_every_intent_at_least_3() -> None:
    """需求方条件一：每个意图 ≥3 条真实问法。"""
    counts: dict[str, int] = {i: 0 for i in INTENTS}
    for _q, expected, _n in CASES:
        counts[expected] += 1
    missing = {i: c for i, c in counts.items() if c < 3}
    assert not missing, f"以下意图问句数 < 3：{missing}"


def test_accuracy_summary(capsys) -> None:
    """条件二：规则路径初步准确率（真实输出，M6 阈值 ≥85% 的前置信号）。"""
    hit = 0
    misses: list[str] = []
    for question, expected, _n in CASES:
        got = _route(question)
        if got == expected:
            hit += 1
        else:
            misses.append(f"「{question}」期望 {expected} 实际 {got}")
    total = len(CASES)
    acc = hit / total
    print(f"\n[intent-routing] 规则路径准确率 = {hit}/{total} = {acc:.1%}（自建问句集）")
    if misses:
        print("[intent-routing] 未命中：\n  " + "\n  ".join(misses))
    assert acc >= 0.85, f"规则路径准确率 {acc:.1%} 低于 85% 前置阈值"


# ---------------------------------------------------------------- 易混对（逐对断言）

@pytest.mark.parametrize(
    "question,expected",
    [
        ("铠被谁克制", "COUNTER_BY"),
        ("谁克制铠", "COUNTER_BY"),
        ("谁能打铠", "COUNTER_BY"),
        ("铠克制谁", "COUNTER_OF"),
        ("铠能打谁", "COUNTER_OF"),
        ("铠压制谁", "COUNTER_OF"),
    ],
)
def test_confusable_counter_by_vs_counter_of(question: str, expected: str) -> None:
    assert _route(question) == expected


@pytest.mark.parametrize(
    "question,expected",
    [
        ("铠怎么玩", "GAMEPLAY"),
        ("铠的打法思路", "GAMEPLAY"),
        ("怎么打铠", "MATCHUP"),
        ("如何打铠", "MATCHUP"),
    ],
)
def test_confusable_gameplay_vs_matchup(question: str, expected: str) -> None:
    assert _route(question) == expected


@pytest.mark.parametrize(
    "question,expected",
    [
        ("铠的出装", "ITEM_BUILD"),
        ("铠的铭文", "INSCRIPTION"),
        ("铠出什么装备", "ITEM_BUILD"),
        ("铠用什么符文", "INSCRIPTION"),
    ],
)
def test_confusable_item_vs_inscription(question: str, expected: str) -> None:
    assert _route(question) == expected


@pytest.mark.parametrize(
    "question,expected",
    [
        ("今天天气怎么样", "OUT_OF_SCOPE"),
        ("帮我写一首诗", "OUT_OF_SCOPE"),
        ("东皇太一", "ENTITY_UNKNOWN"),
        ("铠", "ENTITY_UNKNOWN"),
    ],
)
def test_confusable_out_of_scope_vs_entity_unknown(question: str, expected: str) -> None:
    assert _route(question) == expected


# ---------------------------------------------------------------- 条件五：裁定「谁能针对铠」

def test_who_counters_kai_ruling() -> None:
    """需求方点名的跨意图误判风险：确认并固化裁定。

    「谁能针对铠」要的是**一份压制者名单**，语义同 COUNTER_BY；
    「怎么针对铠」要的是**应对方法**，语义同 MATCHUP。
    两者都含「针对」，靠优先级裁决：_COUNTER_BY 先于 _MATCHUP。
    """
    assert _route("谁能针对铠") == "COUNTER_BY"
    assert _route("怎么针对铠") == "MATCHUP"
    # 「谁能针对铠」同时命中两个词表 -> matched_intents 留痕（条件三）
    r = route("谁能针对铠", use_llm=False)
    assert r.matched_intents[0] == "COUNTER_BY"
    assert "MATCHUP" in r.matched_intents


# ---------------------------------------------------------------- 条件三：多意图命中留痕

def test_multi_intent_hit_is_traced() -> None:
    """「铠的出装和铭文」命中 ITEM_BUILD + INSCRIPTION，只取一个但必须留痕。"""
    r = route("铠的出装和铭文", use_llm=False)
    assert set(r.matched_intents) == {"INSCRIPTION", "ITEM_BUILD"}
    assert r.intent == r.matched_intents[0]  # 取优先级最高者
    assert r.intent == "INSCRIPTION"


def test_single_intent_trace_has_one_entry() -> None:
    r = route("铠被谁克制", use_llm=False)
    assert r.matched_intents == ["COUNTER_BY"]


def test_no_keyword_intent_leaves_trace_empty() -> None:
    """纯实体/越界问句不命中任何词表 -> matched_intents 为空（区分「没命中」与「命中了但没选」）。"""
    assert route("东皇太一", use_llm=False).matched_intents == []
    assert route("今天天气怎么样", use_llm=False).matched_intents == []


# ---------------------------------------------------------------- 独立信号一：规格书 8.1 自带的示例问句
# 这 11 条来自规格书 8.1 评测用例分布表的示例列（作者：需求方，非实现方），
# 期望意图按 8.1 的**类型列**归类，可视为对规则集的一次独立抽检。
SPEC_EXAMPLES: list[tuple[str, str]] = [
    ("铠被谁克制", "COUNTER_BY"),        # 图谱-克制/被克制
    ("谁能打铠", "COUNTER_BY"),          # 图谱-克制/被克制
    ("亚瑟怎么出装", "ITEM_BUILD"),      # 图谱-出装/铭文
    ("貂蝉铭文", "INSCRIPTION"),         # 图谱-出装/铭文
    ("谁和鲁班好配合", "SYNERGY"),       # 图谱-搭档
    ("貂蝉对线思路", "GAMEPLAY"),        # 文本-打法（8.1 归此列；「思路」命中 GAMEPLAY，优先于「对线」的 MATCHUP）
    ("这个版本谁强", "TIER_META"),       # 文本-版本
    ("怎么打东皇", "MATCHUP"),           # 混合-对位
    ("我玩铠怎么打吕布", "MATCHUP"),     # 混合-对位
    ("问个不存在的英雄", "ENTITY_UNKNOWN"),  # 拒答/越界行，但按 9.2-5 实体未识别须澄清
    ("今天天气怎么样", "OUT_OF_SCOPE"),  # 拒答/越界
]


@pytest.mark.parametrize("question,expected", SPEC_EXAMPLES, ids=[c[0] for c in SPEC_EXAMPLES])
def test_spec_example_questions(question: str, expected: str) -> None:
    assert _route(question) == expected


# ---------------------------------------------------------------- 独立信号二：自由口语抽样（暴露规则盲区）
# 这 20 条是**自由口语**问法（用户真实可能输入的样子，非词表里的关键词），用于暴露规则盲区。
# 其中 4 条语义无歧义且高频的问法已据此补入词表（天敌 / 打得过谁 / 咋玩 / 怎么克制）；
# 其余 4 条未命中（见 test_natural_phrasing_sample 的打印）作为 **M6 待补清单**，本阶段不调词表。
NATURAL_SAMPLE: list[tuple[str, str, str]] = [
    ("什么英雄能克制铠", "COUNTER_BY", "「能克制」与「克制谁」冲突，未入词表 -> 盲区"),
    ("铠的天敌是谁", "COUNTER_BY", "已补「天敌」"),
    ("铠打得过谁", "COUNTER_OF", "已补「打得过谁」"),
    ("铠适合和谁走一路", "SYNERGY", "口语「走一路」-> 盲区"),
    ("铠出装怎么选", "ITEM_BUILD", "命中「出装」"),
    ("铠的铭文带什么", "INSCRIPTION", "命中「铭文」"),
    ("铠这英雄咋玩", "GAMEPLAY", "已补「咋玩」"),
    ("铠连招怎么打", "GAMEPLAY", "「连招」优先于「怎么打」"),
    ("打铠用什么英雄", "COUNTER_BY", "口语「用什么英雄」-> 盲区"),
    ("怎么克制铠", "COUNTER_BY", "已补「怎么克制」"),
    ("对面拿铠我选谁", "COUNTER_BY", "口语「拿X我选谁」-> 盲区"),
    ("我玩铠怎么打吕布", "MATCHUP", "命中「怎么打」"),
    ("现在版本哪些英雄强", "TIER_META", "命中「版本」"),
    ("铠值得练吗", "TIER_META", "命中「值得练」"),
    ("铠和谁配合好", "SYNERGY", "命中「配合」"),
    ("铠铭文出装怎么选", "INSCRIPTION", "「铭文」优先于「出装」"),
    ("铠是谁", "ENTITY_UNKNOWN", "纯实体 -> 澄清"),
    ("午饭吃什么", "OUT_OF_SCOPE", "无关话题"),
    ("帮我订张机票", "OUT_OF_SCOPE", "无关话题"),
    ("怎么打铠", "MATCHUP", "命中「怎么打」"),
]


def test_natural_phrasing_sample(capsys) -> None:
    """自由口语抽样的准确率（条件二补充信号；打印真实数字，不设 85% 断言）。"""
    hit = 0
    misses: list[str] = []
    for question, expected, note in NATURAL_SAMPLE:
        got = _route(question)
        if got == expected:
            hit += 1
        else:
            misses.append(f"「{question}」期望 {expected} 实际 {got}（{note}）")
    total = len(NATURAL_SAMPLE)
    acc = hit / total
    print(f"\n[intent-routing] 自由口语抽样准确率 = {hit}/{total} = {acc:.1%}（非验收口径）")
    if misses:
        print("[intent-routing] 口语盲区（M6 待补清单）：\n  " + "\n  ".join(misses))
    assert acc >= 0.5, f"自由口语抽样 {acc:.1%}，低于 50% 说明规则对口语几乎无覆盖"

