"""意图路由 + 槽位抽取（规格书 4.4 / 4.2 步骤 [1]）。

意图枚举**封闭且不可扩展**（4.4 明确「实现方不得私自新增」），故本模块的 `INTENTS`
就是唯一真源，任何下游分支都只能在这 10 个取值里选。

**路由只走确定性规则路径**（决策见 DECISIONS.md 2026-10-14 M2 条与 2026-10-16 移除条）：
意图是封闭枚举、且输入已带实体链接结果（4.3），关键词覆盖足够；确定性 = 可单测、零延迟、
离线可跑（M2 验收项全为确定性断言）。M3 曾预留「意图准确率 < 85% 就切 LLM（Ollama
结构化输出）」的预案，M6 用同一批真实问句实测后**预案被数据否决**（规则 85.1% vs
LLM 36.5%，且规则已达阈值），故 `route_llm` 与 Ollama 依赖按需求方裁定整体移除 ——
一个永远不执行且实测更差的代码路径 = 未测试代码 + 误启用隐患。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

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
    method: str = "rule"          # 恒为 rule（LLM 路径已按 M6 数据裁定移除）
    # 本次问句命中的**全部**意图（按 _RULES 优先级序），intent 取第一个。
    # 需求方 2026-10-15 条件三：多意图命中必须留痕——否则「铠的出装和铭文」只返回 ITEM_BUILD
    # 丢掉 INSCRIPTION 且无任何记录，属静默失败。M6 归因「答案不全」时据此判断是否只取了一个意图。
    matched_intents: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 关键词表

_TIER = ("版本", "强度", "谁强", "上分", "排行", "强势", "t0", "梯队", "值得练")
_INSCRIPTION = ("铭文", "符文")
_ITEM = ("出装", "装备", "出什么", "怎么出", "鞋子", "六神装", "核心装", "第一件")
_GAMEPLAY = ("打法", "玩法", "思路", "连招", "意识", "怎么玩", "咋玩", "技巧", "攻略", "上手", "教程", "教学")
_COUNTER_BY = (
    "被谁克制", "被谁克", "谁克制", "谁压", "被谁压", "怕谁", "被谁打", "被谁counter",
    "被克制", "谁能打", "谁打得过", "怕什么", "被哪些", "天敌", "打不过谁", "怎么克制",
    # 「谁能针对 X」语义是「谁克制 X」（要一份压制者名单），归 COUNTER_BY 而非 MATCHUP。
    # 与 _MATCHUP 的「针对」共存时靠优先级裁决：_COUNTER_BY 先于 _MATCHUP，
    # 「谁能针对铠」→ COUNTER_BY、「怎么针对铠」→ MATCHUP（详见 tests/unit/test_intent_routing.py）。
    "谁能针对", "谁针对", "谁能克", "谁能压制", "谁可以针对", "谁能治", "被什么",
)
_COUNTER_OF = (
    "克制谁", "克制哪", "克谁", "打谁", "压制谁", "能打谁", "克制什么", "欺负谁", "打得过谁",
)
_SYNERGY = ("搭档", "搭配", "配合", "搭配谁", "和谁配", "跟谁配", "组合", "开黑", "一起玩")
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


# 优先级表：既是「先命中先返回」的裁决顺序，也是 matched_intents 的排序依据。
# 「谁能针对铠」一案即由 COUNTER_BY 先于 MATCHUP 裁决（需求方 2026-10-15 审核）。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TIER_META", _TIER),
    ("INSCRIPTION", _INSCRIPTION),
    ("ITEM_BUILD", _ITEM),
    ("GAMEPLAY", _GAMEPLAY),
    ("COUNTER_BY", _COUNTER_BY),
    ("COUNTER_OF", _COUNTER_OF),
    ("SYNERGY", _SYNERGY),
    ("MATCHUP", _MATCHUP),
)


def _matched_intents(t: str) -> list[str]:
    """命中关键词表的所有意图，按 _RULES 优先级序（条件三：多意图留痕用）。"""
    return [name for name, words in _RULES if _hit(t, words)]


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


# ---------------------------------------------------------------- 槽位（路由与继承共用）


def slots_for(intent: str, text: str, entities: list[LinkedEntity]) -> dict:
    """按意图算槽位。路由与指代消解继承（4.10 规则 2「只替换实体」）共用同一实现，
    避免两处口径漂移——这是本项目反复踩过的「同一指标多个口径」类问题。
    """
    heroes = [e for e in entities if e.entity_type == "hero"]
    roles = [e for e in entities if e.entity_type == "role"]
    if intent == "MATCHUP":
        return _matchup_slots(normalize(text), heroes)
    return _base_slots(heroes, roles)


def need_clarify_for(intent: str, slots: dict) -> bool:
    """槽位不完整判定（4.3：MATCHUP 需对位双方，只有一方时澄清反问而非拒答）。"""
    return intent == "MATCHUP" and "hero_ally" not in slots


# ---------------------------------------------------------------- 规则路径


def route_rules(text: str, entities: list[LinkedEntity]) -> IntentResult:
    t = normalize(text)
    heroes = [e for e in entities if e.entity_type == "hero"]
    roles = [e for e in entities if e.entity_type == "role"]

    matched = _matched_intents(t)
    if matched:
        chosen = matched[0]
        if len(matched) > 1:
            # 条件三：多意图命中必须留痕。当前只取第一个、不做合并（需求方明确「不要求现在就做多意图合并」），
            # 但必须看得见——否则「铠的出装和铭文」这类问句会静默丢掉一个意图。
            logger.warning("多意图命中：%r 命中 %s，取 %s（其余仅留痕，未合并）", text, matched, chosen)
        slots = slots_for(chosen, t, entities)
        return IntentResult(
            chosen,
            slots,
            need_clarify=need_clarify_for(chosen, slots),
            method="rule",
            matched_intents=matched,
        )

    if heroes or roles:
        # 认出了实体但没识别出意图（如只输入「东皇太一」）-> 澄清（4.9「槽位不完整」）
        return IntentResult("ENTITY_UNKNOWN", _base_slots(heroes, roles), need_clarify=True, method="rule")
    if _hit(t, _DOMAIN):
        # 有王者语境但实体没认出来 -> 澄清（4.3/9.2-5：绝不允许走拒答）
        return IntentResult("ENTITY_UNKNOWN", {}, need_clarify=True, method="rule")
    return IntentResult("OUT_OF_SCOPE", {}, method="rule")


def route(text: str) -> IntentResult:
    """唯一路由入口：确定性规则路径（LLM 路径已按 M6 数据裁定移除）。"""
    from app.retrieval.entity_linking import link

    return route_rules(text, link(text).entities)
