"""指代消解规则（规格书 4.10）。

**为什么单独成模块**：4.10 的三条规则分处两个阶段——规则 1（指代词继承实体）在实体链接阶段
即可判定，规则 2/3（简短追问继承意图/实体）必须等意图路由给出「本轮意图是否被关键词判定」
之后才能判定。若把判定逻辑分别写在两个节点里，「指代词集合」「简短阈值」「追问标记」
就会有两份定义，任何一处改动都可能漏改另一处（口径漂移）。故集中于此，两节点共用。

规则对照（4.10 原文）：
  1. 当前轮 entities 为空 且 问句含指代词 → 从 last_entities 继承；
  2. 当前轮 intent 无法判定 且 是简短追问（长度 < 8 且含「呢/怎么」）→ 继承 last_intent，只替换实体；
  3. 继承必须**在日志中显式记录**（`coref_resolved`），便于排查与评测。

**实现补充（规则 3，已登记 DECISIONS.md 2026-10-15 M3 条）**：
4.10 的必测链「『貂蝉怕什么』→『怎么打』」是**省略主语**的追问——它既无指代词（规则 1 不适用），
意图又能被「怎么打」关键词判定（规则 2 不适用），但语义上必须继承实体「貂蝉」。
故补一条：当前轮 entities 为空、意图已被关键词判定、且问句是简短追问时，同样继承上一轮实体。
门控条件（必须同时满足）保证不会误伤无关短问句：
  - 无实体：否则无需继承；
  - 命中了意图关键词：否则「今天天气怎么样」这类短问句会被错误继承；
  - 简短（长度 < COREF_SHORT_LEN）：长问句自带完整语境，不应继承。
"""
from __future__ import annotations

import logging

from app.config import settings
from app.retrieval.entity_linking import entity_by_id
from app.retrieval.intent import normalize
from app.schemas.entity import LinkedEntity

logger = logging.getLogger(__name__)

# 指代词（4.10 规则 1 点名「他/她/它/这个/那个/那……呢」）。
# 按长度降序排列，保证「这个」不会被单字「这」截断成半个词。
PRONOUNS: tuple[str, ...] = ("这些", "那些", "这个", "那个", "他", "她", "它", "那", "其")

# 简短追问的标记词（4.10 规则 2 写「含『呢/怎么』」）。
# 这里**刻意不收「怎么」**：「今天天气怎么样」含「怎么」但显然是越界问句，
# 收进去会把无关问句误判为追问并继承上一轮意图（静默串味）。
# 改用「呢 / 还有 / 那么」——它们几乎只出现在追问语境，误报面小得多。
FOLLOWUP_MARKERS: tuple[str, ...] = ("呢", "还有", "那么")


def first_pronoun(text: str) -> str | None:
    norm = normalize(text)
    for p in PRONOUNS:
        if p in norm:
            return p
    return None


def is_short(text: str) -> bool:
    """4.10 规则 2 的「长度 < 8 字」阈值，取自 config（9.1-2：不硬编码）。"""
    return len(normalize(text)) < settings.COREF_SHORT_LEN


def has_followup_marker(text: str) -> bool:
    norm = normalize(text)
    return any(m in norm for m in FOLLOWUP_MARKERS)


def inherit_entities(question: str, last_ids: list[str]) -> tuple[list[LinkedEntity], str]:
    """按上一轮规范 ID 继承实体，并返回「消解后问句」的可读形态。

    返回 (继承到的实体, 消解后问句)。查不到 ID 对应实体时不编造桩实体，直接返回空列表。
    例：「那铭文呢」+ last=[铠] → 「铠铭文呢」；无指代词时改为前置：「貂蝉怎么打」。
    """
    inherited: list[LinkedEntity] = []
    for eid in last_ids:
        ent = entity_by_id(eid)
        if ent is not None:
            inherited.append(ent)
    if not inherited:
        return [], question

    names = "、".join(e.canonical_name or e.raw for e in inherited)
    pron = first_pronoun(question)
    resolved = question.replace(pron, names, 1) if pron else names + question
    return inherited, resolved
