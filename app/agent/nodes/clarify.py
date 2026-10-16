"""节点 [6a/6b]：澄清反问与拒答（规格书 4.3 / 4.9）。

**澄清 ≠ 拒答**（1.8 的静默失败分析、9.2-5）：实体没认出来和知识库真没数据，在用户看来
长得一样，但处理方式相反。实体异常必须走**澄清**（给候选让用户挑），只有「与王者无关」才拒答。

**可选 human-in-the-loop（4.8-7）**：`hitl=True` 时澄清节点用 `interrupt()` 暂停图执行，
等用户补充信息后 `Command(resume=...)` 继续。默认 False——M6 评测脚本要批量跑分，
每条澄清都挂起会卡死评测。该分支由 `tests/integration/test_graph_coref.py` 真实触发并断言。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from langgraph.types import interrupt

from app.agent.state import AgentState
from app.retrieval.neo4j_client import GraphUnavailable, run_template

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 澄清候选的本地兜底清单：Neo4j 不可用或用户没给分路时，至少给出常见英雄让用户能继续。
# 不用「heroes.json 前 8 个」——文件顺序没有语义，给出来的候选会很随机。
_POPULAR = ("亚瑟", "后羿", "鲁班七号", "貂蝉", "铠", "东皇太一", "兰陵王", "蔡文姬", "孙悟空", "安琪拉")


def _entity_names(state: AgentState) -> list[str]:
    """本轮已认出的实体名（顺序即其在问句中的出现顺序）。"""
    return [e.canonical_name or e.raw for e in (state.get("entities") or [])]


def _hero_candidates(state: AgentState) -> list[str]:
    """英雄候选清单：优先按分路从图谱取（4.7 的 HEROES_BY_ROLE 模板正是为澄清设计的）。"""
    role = (state.get("slots") or {}).get("role")
    if role:
        try:
            rows = run_template("HEROES_BY_ROLE", role=role, limit=8)
            names = [r["name"] for r in rows]
            if names:
                return names
        except GraphUnavailable as e:
            logger.info("澄清候选：图谱不可用，回落本地清单（%s）", e)

    try:
        data = json.loads((PROJECT_ROOT / "data" / "graph" / "heroes.json").read_text(encoding="utf-8"))
        known = {h["name"] for h in data}
    except Exception as e:  # noqa: BLE001 - 候选清单是兜底，读不到也不能让链路断
        logger.warning("澄清候选：本地英雄清单读取失败：%s", e)
        known = set()

    picked = [n for n in _POPULAR if n in known]
    return picked or sorted(known)[:8]


def _candidates(state: AgentState) -> list[str]:
    """澄清候选。

    D1 缺陷（2026-10-16）前，本函数在**没有 role 槽位时一律返回 `_POPULAR` 十人清单**——
    该清单与用户输入无关，于是「克制关系」与「镜的克制关系」两张澄清卡的候选完全一样，
    用户看到的是「系统没在听我说话」。修复原则：**候选必须与本轮输入相关**。

    三类候选，按澄清场景分派：
      1. MATCHUP 缺我方英雄 —— 需要用户挑一个英雄，仍是英雄清单（沿用原逻辑）；
      2. 已认出实体 + 关系类无方向问法（`clarify_kind`）—— 候选是**方向问句**，点一下就能拿到答案；
      3. 已认出实体 —— 候选是锚定该英雄的**问句模板**，而不是一份与输入无关的英雄名单
         （否则用户点「东皇太一」又会回到同一张澄清卡，形成死循环）；
      4. 一个实体都没认出 —— 才是英雄清单真正该出现的场景（用户打错了英雄名，给正确候选让他挑）。
    """
    kind = state.get("clarify_kind") or ""
    names = _entity_names(state)

    if state.get("intent") == "MATCHUP" and (state.get("slots") or {}).get("hero_enemy_name"):
        return _hero_candidates(state)

    if names and kind in ("counter_direction", "relation_direction"):
        hero = names[0]
        options = [f"{hero}克制谁", f"谁克制{hero}"]
        if kind == "relation_direction":
            # 只说「关系」时连是克制还是搭档都不确定，把搭档一并列为候选（见 intent._RELATION_TOPIC）
            options.append(f"{hero}的搭档")
        return options

    if names:
        hero = names[0]
        return [f"{hero}克制谁", f"谁克制{hero}", f"{hero}怎么出装", f"{hero}的铭文", f"{hero}怎么玩"]

    return _hero_candidates(state)


def _clarify_question(state: AgentState) -> str:
    """澄清反问文案。

    **分支顺序即语义**（D1 缺陷 L2 的根因）：原来的顺序把 `unrecognized` 排在 `entities` 之前，
    于是「英雄已认出 + 另有未识别残句」时，系统会问出「没认出「关系」，你是指下面哪个英雄？」
    ——既把话题词当英雄问，又无视了已经认出的「镜」。`unrecognized` 分支真正的适用场景是
    **一个实体都没认出**（如「没认出凯旋门」），此时 `entities` 为空，调换顺序不影响它。
    """
    intent = state.get("intent", "")
    slots = state.get("slots") or {}
    entities = list(state.get("entities") or [])
    unrecognized = list(state.get("unrecognized") or [])
    kind = state.get("clarify_kind") or ""

    if intent == "MATCHUP" and slots.get("hero_enemy_name"):
        # 4.3 点名的「怎么打东皇」场景：只有敌方时问「你想用哪个英雄对线东皇？」
        return f"你想用哪个英雄对线{slots['hero_enemy_name']}？"
    if entities and kind == "counter_direction":
        names = "、".join(_entity_names(state))
        return f"「{names}」的克制关系有两个方向，你想问哪个？（{names}克制谁 / 谁克制{names}）"
    if entities and kind == "relation_direction":
        names = "、".join(_entity_names(state))
        return (
            f"「{names}」的关系有好几种，你想问哪一种？"
            f"（{names}克制谁 / 谁克制{names} / {names}的搭档）"
        )
    if entities:
        names = "、".join(_entity_names(state))
        return f"你想问「{names}」的什么？（克制关系 / 出装 / 铭文 / 打法）"
    if unrecognized:
        return f"没认出「{'、'.join(unrecognized)}」，你是指下面哪个英雄？"
    if kind:
        # 「克制关系」这种只给了话题、没给英雄的问法：缺的是英雄而不是方向，故问「哪个英雄的」。
        return f"你想问哪个英雄的{'克制关系' if kind == 'counter_direction' else '关系'}？"
    return "请补充你想问的英雄或具体问题。"


def clarify_node(state: AgentState) -> dict:
    options = _candidates(state)
    question = _clarify_question(state)

    if state.get("hitl"):
        # 4.8-7 加分项：暂停图执行等用户补充，resume 后 interrupt 返回用户的选择
        choice = interrupt({"type": "clarify", "question": question, "options": options})
        logger.info("human-in-the-loop 已恢复：用户补充 = %r", choice)
        return {
            "response_type": "clarify",
            "clarify_options": options,
            "answer": f"{question}\n（已收到补充：{choice}）",
            "citations": [],
            "confidence": 0.0,
        }

    logger.info("澄清反问：%s（候选 %d 个）", question, len(options))
    return {
        "response_type": "clarify",
        "clarify_options": options,
        "answer": question,
        "citations": [],
        "confidence": 0.0,
    }


def reject_node(state: AgentState) -> dict:
    """拒答（4.9「无依据」档 + OUT_OF_SCOPE）。必须给出可替代的提问方向。"""
    if state.get("intent") == "OUT_OF_SCOPE":
        answer = (
            "这个问题与王者荣耀无关，我无法回答。"
            "你可以问我英雄的克制关系（「铠被谁克制」）、出装（「亚瑟怎么出装」）、"
            "铭文、打法或版本强度。"
        )
    else:
        answer = (
            "知识库中没有收录与该问题相关的内容，暂时无法给出有依据的回答。"
            "可以换一个英雄或换一种问法（如「貂蝉的铭文搭配」）再试。"
        )

    logger.info("拒答：intent=%s", state.get("intent"))
    return {"answer": answer, "citations": [], "confidence": 0.0, "response_type": "reject"}
