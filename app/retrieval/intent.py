"""意图路由 + 槽位抽取（规格书 4.4 / 4.2 步骤 [1]）。

意图枚举**封闭且不可扩展**（4.4 明确「实现方不得私自新增」），故本模块的 `INTENTS`
就是唯一真源，任何下游分支都只能在这 10 个取值里选。

两条路径（决策见 DECISIONS.md 2026-10-14 M2 条）：
  - **规则路径（默认）**：确定性关键词分类。意图是封闭枚举、且输入已带实体链接结果（4.3），
    关键词覆盖足够；确定性 = 可单测、零延迟、离线可跑（M2 验收项全为确定性断言）。
  - **LLM 路径（可选）**：Ollama 结构化输出（4.11 选型 qwen2.5:3b）。`use_llm=True` 时启用，
    失败/超时/输出非法一律**回落规则路径**（9.1-3：外部调用必须有超时与异常处理）。

M2 交付报告会把这个取舍单独列出，请需求方确认。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.retrieval.entity_linking import normalize
from app.schemas.entity import LinkedEntity

logger = logging.getLogger(__name__)

# 封闭枚举（规格书 4.4）——不得新增
INTENTS = (
    "COUNTER_BY",      # X 被谁克制（反向边）
    "COUNTER_OF",      # X 克制谁（正向边）
    "SYNERGY",         # X 的搭档
    "ITEM_BUILD",      # X 怎么出装
    "INSCRIPTION",     # X 用什么铭文
    "GAMEPLAY",        # X 的打法/意识/连招
    "MATCHUP",         # 怎么打 Y / 对线 Y
    "TIER_META",       # 版本强度、版本理解
    "ENTITY_UNKNOWN",  # 实体未识别 -> 澄清
    "OUT_OF_SCOPE",    # 与王者无关 -> 拒答
)


@dataclass
class IntentResult:
    intent: str
    slots: dict = field(default_factory=dict)
    need_clarify: bool = False
    method: str = "rule"          # rule | llm


# ---------------------------------------------------------------- 关键词表

_TIER = ("版本", "强度", "谁强", "上分", "排行", "强势", "t0", "梯队", "值得练")
_INSCRIPTION = ("铭文", "符文")
_ITEM = ("出装", "装备", "出什么", "怎么出", "鞋子", "六神装", "核心装", "第一件")
_GAMEPLAY = ("打法", "玩法", "思路", "连招", "意识", "怎么玩", "技巧", "攻略", "上手", "教程", "教学")
_COUNTER_BY = (
    "被谁克制", "被谁克", "谁克制", "谁压", "被谁压", "怕谁", "被谁打", "被谁counter",
    "被克制", "谁能打", "谁打得过", "怕什么", "被哪些",
)
_COUNTER_OF = ("克制谁", "克制哪", "克谁", "打谁", "压制谁", "能打谁", "克制什么", "欺负谁")
_SYNERGY = ("搭档", "配合", "搭配谁", "和谁配", "跟谁配", "组合", "开黑", "一起玩")
_MATCHUP = ("怎么打", "如何打", "咋打", "对线", "怎么对", "克制我", "针对", "怎么破", "如何破")

# 判定「与王者有关」的宽口径词表（用于把「今天天气怎么样」判成 OUT_OF_SCOPE，
# 而不是 ENTITY_UNKNOWN——两者的下游分支相反：前者拒答、后者澄清，4.9 已区分）。
_DOMAIN = (
    "克制", "压制", "被克制", "出装", "装备", "铭文", "符文", "打野", "射手", "辅助",
    "中单", "对抗路", "发育路", "游走", "上单", "边路", "英雄", "王者", "荣耀", "技能",
    "连招", "搭档", "配合", "版本", "上分", "对线", "分路", "排位", "开黑", "打野",
)


def _hit(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


# ---------------------------------------------------------------- 槽位


def _hero_positions(text: str, heroes: list[LinkedEntity]) -> list[tuple[int, LinkedEntity]]:
    """按实体在文本中首次出现的位置排序（用于区分 MATCHUP 的我方/敌方）。"""
    out: list[tuple[int, LinkedEntity]] = []
    cursor = 0
    for e in heroes:
        idx = text.find(e.raw, cursor)
        if idx < 0:
            idx = text.find(e.raw)
        if idx < 0:
            idx = cursor
        out.append((idx, e))
        cursor = max(cursor, idx + len(e.raw))
    out.sort(key=lambda p: p[0])
    return out


def _matchup_slots(text: str, heroes: list[LinkedEntity]) -> dict:
    """MATCHUP：关键字（怎么打/对线/针对）之前的是我方，之后的是敌方（4.4）。"""
    kw_re = re.compile("|".join(re.escape(w) for w in _MATCHUP))
    m = kw_re.search(text)
    kw_pos = m.start() if m else len(text)
    positioned = _hero_positions(text, heroes)
    ally = [e for pos, e in positioned if pos < kw_pos]
    enemy = [e for pos, e in positioned if pos >= kw_pos]
    slots: dict = {}
    if enemy:
        slots["hero_enemy"] = enemy[0].canonical_id
        slots["hero_enemy_name"] = enemy[0].canonical_name
    if ally:
        slots["hero_ally"] = ally[0].canonical_id
        slots["hero_ally_name"] = ally[0].canonical_name
    return slots


def _base_slots(heroes: list[LinkedEntity], roles: list[LinkedEntity]) -> dict:
    slots: dict = {}
    if heroes:
        slots["hero"] = heroes[0].canonical_id
        slots["hero_name"] = heroes[0].canonical_name
    if roles:
        slots["role"] = roles[0].canonical_name
    return slots


# ---------------------------------------------------------------- 规则路径


def route_rules(text: str, entities: list[LinkedEntity]) -> IntentResult:
    t = normalize(text)
    heroes = [e for e in entities if e.entity_type == "hero"]
    roles = [e for e in entities if e.entity_type == "role"]

    if _hit(t, _TIER):
        return IntentResult("TIER_META", _base_slots(heroes, roles), method="rule")
    if _hit(t, _INSCRIPTION):
        return IntentResult("INSCRIPTION", _base_slots(heroes, roles), method="rule")
    if _hit(t, _ITEM):
        return IntentResult("ITEM_BUILD", _base_slots(heroes, roles), method="rule")
    if _hit(t, _GAMEPLAY):
        return IntentResult("GAMEPLAY", _base_slots(heroes, roles), method="rule")
    if _hit(t, _COUNTER_BY):
        return IntentResult("COUNTER_BY", _base_slots(heroes, roles), method="rule")
    if _hit(t, _COUNTER_OF):
        return IntentResult("COUNTER_OF", _base_slots(heroes, roles), method="rule")
    if _hit(t, _SYNERGY):
        return IntentResult("SYNERGY", _base_slots(heroes, roles), method="rule")
    if _hit(t, _MATCHUP):
        slots = _matchup_slots(t, heroes)
        # 4.3：MATCHUP 需要两个英雄（对位双方）。只有敌方时槽位不完整 -> 澄清反问。
        return IntentResult("MATCHUP", slots, need_clarify="hero_ally" not in slots, method="rule")

    if heroes or roles:
        # 认出了实体但没识别出意图（如只输入「东皇太一」）-> 澄清（4.9「槽位不完整」）
        return IntentResult("ENTITY_UNKNOWN", _base_slots(heroes, roles), need_clarify=True, method="rule")
    if _hit(t, _DOMAIN):
        # 有王者语境但实体没认出来 -> 澄清（4.3/9.2-5：绝不允许走拒答）
        return IntentResult("ENTITY_UNKNOWN", {}, need_clarify=True, method="rule")
    return IntentResult("OUT_OF_SCOPE", {}, method="rule")


# ---------------------------------------------------------------- LLM 路径


_LLM_SYSTEM = (
    "你是王者荣耀问答系统的意图分类器。只能从下面 10 个意图里选一个，不得新增：\n"
    + "、".join(INTENTS)
    + "\n只输出 JSON：{\"intent\": \"<意图>\", \"hero\": \"<主英雄规范名或空>\"}。不要解释。"
)


def route_llm(text: str, entities: list[LinkedEntity]) -> IntentResult | None:
    """Ollama 结构化输出。失败/超时/输出非法返回 None（由调用方回落规则路径）。"""
    import httpx

    known = "、".join(e.canonical_name or e.raw for e in entities) or "（无）"
    payload = {
        "model": settings.INTENT_MODEL,
        "prompt": f"已知实体：{known}\n用户问题：{text}",
        "system": _LLM_SYSTEM,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    resp = httpx.post(
        f"{settings.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=settings.LLM_TIMEOUT
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    data = json.loads(raw)
    intent = str(data.get("intent", "")).strip()
    if intent not in INTENTS:
        logger.warning("LLM 返回非法意图 %r，回落规则路径", intent)
        return None

    heroes = [e for e in entities if e.entity_type == "hero"]
    roles = [e for e in entities if e.entity_type == "role"]
    slots = _base_slots(heroes, roles)
    if intent == "MATCHUP":
        slots = _matchup_slots(normalize(text), heroes)
    return IntentResult(intent, slots, need_clarify=False, method="llm")


def route(text: str, *, use_llm: bool = False) -> IntentResult:
    """默认走确定性规则路径；use_llm=True 时先试 LLM，任何失败都回落规则。"""
    from app.retrieval.entity_linking import link

    entities = link(text).entities
    if use_llm:
        try:
            llm = route_llm(text, entities)
            if llm is not None:
                return llm
        except Exception as e:  # noqa: BLE001 - LLM 是可选增强，任何异常都不能中断链路
            logger.warning("LLM 意图路由失败，回落规则路径：%s", e)
    return route_rules(text, entities)
