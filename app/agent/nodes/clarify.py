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


def _candidates(state: AgentState) -> list[str]:
    """澄清候选：优先按分路从图谱取（4.7 的 HEROES_BY_ROLE 模板正是为澄清设计的）。"""
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


def _clarify_question(state: AgentState) -> str:
    intent = state.get("intent", "")
    slots = state.get("slots") or {}
    entities = list(state.get("entities") or [])
    unrecognized = list(state.get("unrecognized") or [])

    if intent == "MATCHUP" and slots.get("hero_enemy_name"):
        # 4.3 点名的「怎么打东皇」场景：只有敌方时问「你想用哪个英雄对线东皇？」
        return f"你想用哪个英雄对线{slots['hero_enemy_name']}？"
    if unrecognized:
        return f"没认出「{'、'.join(unrecognized)}」，你是指下面哪个英雄？"
    if entities:
        names = "、".join(e.canonical_name or e.raw for e in entities)
        return f"你想问「{names}」的什么？（克制关系 / 出装 / 铭文 / 打法）"
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
