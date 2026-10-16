"""D1 缺陷回归测试（2026-10-16 · 「关系」类问法被误判为英雄未识别）。

对应缺陷报告 §4 的验收要求，三项：

  1. **防漂移测试**（L1 根因的守门人）：遍历意图层话题词的唯一真源 `intent.topic_words()`，
     断言每个词都不会出现在 `link(f"铠{w}")` 的 `unrecognized` 里。以后意图关键词表加词、
     而实体链接层的停用词表没同步时，本测试会**立刻失败**，而不是等用户撞上
     （D1 的 L1 根因正是「同一件事两份维护」——意图表加了词、停用词表没跟）。

  2. **关系类问法的澄清必须是「方向澄清」**：`clarify_kind` 被标记，文案与候选都锚定已认出的英雄。
     ⚠️ 缺陷报告 §4 原写「断言 need_clarify=False」，但需求方 2026-10-16 已裁定走
     **方向澄清**（反问「镜克制谁」还是「谁克制镜」，不新增意图、不动 4.4 的封闭枚举），
     故此处按裁定断言：澄清类型被正确标记、候选是**可直接点选的方向问句**（点一下即得答案），
     且文案不再出现「没认出『关系』」。

  3. **防 L2 改过头**：一个实体都没认出的真未识别场景，仍必须走澄清（4.3/9.2-5：绝不走拒答）。

全部为确定性断言，不调用大模型、不依赖 Neo4j / Chroma，可离线跑。
"""
from __future__ import annotations

import pytest

from app.agent.nodes.clarify import _candidates, _clarify_question
from app.retrieval import intent as intent_mod
from app.retrieval.entity_linking import link
from app.retrieval.intent import route_rules


def _state(question: str) -> dict:
    """按节点真实入参构造 State（直接复用 link + route_rules，不重写一遍口径）。"""
    res = link(question)
    routed = route_rules(question, res.entities)
    return {
        "question": question,
        "entities": res.entities,
        "unrecognized": res.unrecognized,
        "intent": routed.intent,
        "slots": routed.slots,
        "need_clarify": routed.need_clarify,
        "clarify_kind": routed.clarify_kind,
    }


def _names(question: str) -> list[str]:
    return [e.canonical_name for e in link(question).entities]


# ---------------------------------------------------------------- 1. 防漂移


def test_topic_words_is_not_empty():
    """防漂移测试本身不能空转：唯一真源必须真的有一批词（否则下面的遍历是空断言）。"""
    words = intent_mod.topic_words()
    assert len(words) >= 50, f"话题词唯一真源只有 {len(words)} 个词，防漂移遍历等于没测"


def test_topic_words_never_leak_into_unrecognized():
    """意图层每一个话题词，都不允许在 `link("铠" + 词)` 的 unrecognized 里冒出来。

    这是「同一件事两份维护」的机制性防线：`entity_linking.stopwords()` 只 union
    `intent.topic_words()`，本测试把这条约定钉死——任何一边加了词、另一边没同步，
    残句里就会冒出这个话题词，测试立刻红。
    """
    leaks: list[str] = []
    for w in intent_mod.topic_words():
        got = link(f"铠{w}").unrecognized
        if w in got:
            leaks.append(f"{w!r} 泄漏为未识别残句（link('铠{w}') -> {got}）")
    assert not leaks, "以下话题词被当成疑似实体，说明停用词表与意图词表漂移：\n  " + "\n  ".join(leaks)


# ---------------------------------------------------------------- 2. 关系类问法


# 「XX的克制关系」「XX的关系」「XX关系」——需求方点名必须覆盖的三种写法
RELATION_PHRASINGS: list[tuple[str, str, str]] = [
    ("镜的克制关系", "镜", "counter_direction"),
    ("铠的克制关系", "铠", "counter_direction"),
    ("镜的关系", "镜", "relation_direction"),
    ("铠关系", "铠", "relation_direction"),
]


@pytest.mark.parametrize("question,hero,kind", RELATION_PHRASINGS, ids=[c[0] for c in RELATION_PHRASINGS])
def test_relation_phrasing_marks_direction_clarify(question: str, hero: str, kind: str) -> None:
    """实体必须被认出（不再丢），且澄清类型被标记为「方向待定」。"""
    st = _state(question)
    assert _names(question) == [hero], f"{question!r} 实体识别失败"
    assert st["unrecognized"] == [], f"{question!r} 残句应为空，实际 {st['unrecognized']}"
    assert st["intent"] == "ENTITY_UNKNOWN"
    assert st["clarify_kind"] == kind, f"{question!r} clarify_kind 期望 {kind}，实际 {st['clarify_kind']!r}"


@pytest.mark.parametrize("question,hero,_kind", RELATION_PHRASINGS, ids=[c[0] for c in RELATION_PHRASINGS])
def test_relation_clarify_question_keeps_hero_and_drops_unrecognized_wording(
    question: str, hero: str, _kind: str
) -> None:
    """澄清文案必须锚定已认出的英雄，且不再出现「没认出『关系』」这种把话题词当英雄的问法。"""
    q = _clarify_question(_state(question))
    assert "没认出" not in q, f"{question!r} 仍在把话题词当未识别英雄反问：{q}"
    assert hero in q, f"{question!r} 的澄清文案没带上已认出的英雄：{q}"


def test_relation_clarify_candidates_are_clickable_direction_phrases():
    """候选必须是**可直接点选的方向问句**——点一下就能拿到答案，澄清不再是死胡同。"""
    assert _candidates(_state("镜的克制关系")) == ["镜克制谁", "谁克制镜"]
    # 只说「关系」时连是克制还是搭档都不确定，把搭档一并列出
    assert _candidates(_state("镜的关系")) == ["镜克制谁", "谁克制镜", "镜的搭档"]


def test_candidates_differ_between_hero_and_no_hero_relation_question():
    """D1 的直接观感来源：原来两张澄清卡的候选都是同一份固定英雄名单。

    修复后候选必须与输入相关——有英雄的关系问法给方向问句，无英雄的才给英雄清单。
    """
    with_hero = _candidates(_state("镜的克制关系"))
    without_hero = _candidates(_state("克制关系"))
    assert with_hero != without_hero, "两张澄清卡的候选仍然一样，说明候选还是与输入无关的固定名单"
    assert "镜克制谁" in with_hero
    assert "镜克制谁" not in without_hero


@pytest.mark.parametrize(
    "candidate,expected",
    [("镜克制谁", "COUNTER_OF"), ("谁克制镜", "COUNTER_BY"), ("镜的搭档", "SYNERGY")],
)
def test_direction_candidate_is_a_working_question(candidate: str, expected: str) -> None:
    """点选候选后必须落到一个真实可答的意图上（澄清卡不再是死循环）。"""
    assert route_rules(candidate, link(candidate).entities).intent == expected


def test_relation_without_hero_asks_which_hero():
    """「克制关系」这种只给话题、没给英雄的问法：缺的是英雄，不是方向。"""
    st = _state("克制关系")
    assert st["entities"] == [] and st["unrecognized"] == []
    assert st["clarify_kind"] == "counter_direction"
    q = _clarify_question(st)
    assert "哪个英雄" in q, f"无英雄的关系问法应问「哪个英雄的克制关系」，实际：{q}"
    assert _candidates(st), "无英雄时应给英雄候选清单"


def test_synergy_relation_phrase_answers_without_clarify():
    """「镜的搭档关系」有明确方向（搭档），必须直接答 SYNERGY，且残句为空（报告 §4 验收第 3 条）。"""
    st = _state("镜的搭档关系")
    assert st["intent"] == "SYNERGY"
    assert st["need_clarify"] is False
    assert st["unrecognized"] == []
    assert _names("镜的搭档关系") == ["镜"]


# ---------------------------------------------------------------- 3. 防 L2 改过头


def test_pure_unrecognized_still_clarifies():
    """一个实体都没认出的真未识别场景，仍必须走澄清（防 L2 把顺序调过头）。"""
    q = "赛博坦这个英雄怎么样"
    st = _state(q)
    assert st["entities"] == []
    assert st["unrecognized"] == ["赛博坦"]
    assert st["need_clarify"] is True
    assert st["intent"] == "ENTITY_UNKNOWN"
    text = _clarify_question(st)
    assert "没认出" in text and "赛博坦" in text, f"真未识别场景的反问文案不对：{text}"
    assert _candidates(st), "未识别场景必须给英雄候选清单"


def test_kai_rotating_door_still_clarifies_not_rejects():
    """「没认出凯旋门」：即便残句形态不理想，也**必须澄清**（4.3/9.2-5 绝不允许走拒答）。

    注：这里 `铠` 会被「凯旋门」里的别名「凯」误命中——这是实体链接层**已知且已登记**的
    单字实体局限（见 `app/retrieval/entity_linking.py` 模块 docstring），不在 D1 三层根因范围内。
    本用例只钉住「仍走澄清」这一条，不把误命中当成正确行为。
    """
    st = _state("没认出凯旋门")
    assert st["intent"] == "ENTITY_UNKNOWN"
    assert st["need_clarify"] is True


def test_entity_branch_takes_priority_over_unrecognized():
    """L2 的核心断言：英雄已认出 + 另有未识别残句时，反问的是**英雄**，不是残句。

    原实现顺序颠倒，会问出「没认出『老婆』，你是指下面哪个英雄？」——既答非所问，
    又把已经认出的「铠」丢了。
    """
    q = "铠的老婆是谁"
    st = _state(q)
    assert _names(q) == ["铠"]
    assert st["unrecognized"] == ["老婆"], "本用例需要一个「英雄已认出 + 有残句」的输入"
    text = _clarify_question(st)
    assert "没认出" not in text, f"顺序仍颠倒：{text}"
    assert "铠" in text
    assert all("铠" in opt for opt in _candidates(st)), "候选必须锚定已认出的英雄"
