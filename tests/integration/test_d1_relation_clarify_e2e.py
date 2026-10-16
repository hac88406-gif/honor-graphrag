"""D1 缺陷编排级回归（2026-10-16 · 「关系」类问法被误判为英雄未识别）。

缺陷的**发现场景是前端聊天页手测**，故除 `tests/unit/test_d1_relation_clarify.py` 的
规则层断言外，还需一条走**完整编排图**的用例，确认澄清卡真的带着方向候选回到用户面前。

澄清路径在检索之前分流（`app/agent/graph.py::route_after_intent`），因此本文件**不需要 Neo4j / Chroma**。
"""
from __future__ import annotations


async def test_relation_question_card_carries_direction_candidates(ask):
    """「镜的克制关系」：候选必须是锚定「镜」的方向问句，而不是一份与输入无关的英雄名单。"""
    s = await ask("d1-rel", "镜的克制关系")

    assert s["response_type"] == "clarify"
    assert [e.canonical_name for e in s["entities"]] == ["镜"], "已认出的实体不得被丢掉"
    assert s["unrecognized"] == [], "话题词「关系」不得再成为未识别残句"
    assert s["clarify_options"] == ["镜克制谁", "谁克制镜"]
    assert "没认出" not in s["answer"], f"仍在把话题词当英雄反问：{s['answer']}"
    assert "镜" in s["answer"]


async def test_recognized_entity_card_is_anchored_on_that_entity(ask):
    """已认出实体的澄清卡：候选锚定该英雄（原来是「克制关系」与「镜的克制关系」两张一样的卡）。"""
    s = await ask("d1-hero", "东皇太一")

    assert s["response_type"] == "clarify"
    assert s["clarify_options"], "澄清必须给候选（否则前端无法渲染可点选项）"
    assert all("东皇太一" in opt for opt in s["clarify_options"]), (
        f"候选未锚定已认出的英雄：{s['clarify_options']}"
    )


async def test_pure_unrecognized_card_still_offers_hero_list(ask):
    """真未识别场景仍走澄清，并给出英雄候选清单（防 L2 把分支顺序调过头）。"""
    s = await ask("d1-unknown", "赛博坦这个英雄怎么样")

    assert s["response_type"] == "clarify"
    assert s["entities"] == []
    assert s["unrecognized"] == ["赛博坦"]
    assert "没认出" in s["answer"] and "赛博坦" in s["answer"]
    assert s["clarify_options"], "未识别场景必须给英雄候选"
    assert "亚瑟" in s["clarify_options"]
