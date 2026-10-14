"""实体链接层（规格书 4.3 / 1.8）。

把用户口语输入映射到图谱规范实体 ID。**规则优先，不调用大模型**（4.3 已裁定）：
别名表与拼音模糊匹配都是确定性的，可单测、可缓存、零延迟；交给 LLM 只会引入延迟与不稳定。

三级策略，按顺序执行、命中即停（4.3）：
  1. 精确匹配  —— 归一化后的字符串直接命中规范名
  2. 别名表匹配 —— data/hero_aliases.json（简称/俗称、同音错字、昵称/梗）+ 分路口语
  3. 模糊匹配  —— 先拼音转换（pypinyin），再对拼音**音节序列**做编辑距离 ≤ 2；
                 仅在前两级全失败时启用，且置信度需 ≥ ENTITY_CONFIDENCE_THRESHOLD 才采纳

归一化（4.2 步骤 0）：繁简归一（内置常用繁→简表）+ 全半角归一（NFKC）+ 去空白。

为什么模糊匹配用「音节序列编辑距离」而不是「整串字符编辑距离」：
用户打错字时错的是**同音/近音字**（凯→铠、貂禅→貂蝉、兰凌王→兰陵王、后一→后羿），
音节序列能把这类错误直接归零（拼音完全相同），比字符编辑距离更贴合中文输入错误分布。

已知局限（写进 M2 报告，不掩盖）：单字实体（铠/瑶/镜/影/曜/澜/苍/暃、别名 凯/鲲）在
「电影」「眼镜」「凯旋」这类普通词里会被误命中。本项目的输入域是王者荣耀问答，
这类词出现概率极低；若 M6 评测发现误报，再补上下文黑名单。
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.schemas.entity import LinkedEntity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HEROES_FILE = PROJECT_ROOT / "data" / "graph" / "heroes.json"
ITEMS_FILE = PROJECT_ROOT / "data" / "graph" / "items.json"
INSCRIPTIONS_FILE = PROJECT_ROOT / "data" / "graph" / "inscriptions.json"
ALIASES_FILE = PROJECT_ROOT / "data" / "hero_aliases.json"

# 常用「繁体 -> 简体」映射。只收本项目实体名里真实出现过的繁体字形，
# 不做通用繁简转换（那需要 opencc 级词表，超出本层需要）。
TRAD_TO_SIMP = {
    "鎧": "铠", "蟬": "蝉", "禪": "禅", "飛": "飞", "蘭": "兰", "華": "华", "韓": "韩",
    "張": "张", "孫": "孙", "臏": "膑", "趙": "赵", "雲": "云", "諸": "诸", "關": "关",
    "項": "项", "劉": "刘", "備": "备", "呂": "吕", "馬": "马", "則": "则", "媧": "娲",
    "後": "后", "軻": "轲", "魯": "鲁", "號": "号", "萊": "莱", "夢": "梦", "豬": "猪",
    "兒": "儿", "鵲": "鹊", "隱": "隐", "亞": "亚", "連": "连", "喬": "乔", "緣": "缘",
    "鏡": "镜", "奧": "奥", "豔": "艳", "鍾": "钟", "離": "离", "漸": "渐", "宮": "宫",
    "盧": "卢", "啟": "启", "諾": "诺", "蒼": "苍", "鐵": "铁", "蘇": "苏", "頗": "颇",
    "莊": "庄", "將": "将", "盤": "盘", "楊": "杨", "環": "环", "東": "东", "瑤": "瑶",
    "瀾": "澜", "蓮": "莲", "觀": "观", "權": "权", "寧": "宁", "鳳": "凤", "靈": "灵",
}

# 分路 / 位置口语 -> 规范分路名（规格书 4.3 第 2 级必须覆盖）。
# 只做「多对一」归并，不新增分路枚举（分路取值沿用抓取脚本 ROLE_CODE_TO_LANE 的五个）。
#
# **不收单字别名「上」「中」**：它们会在「上海」「中国」这类与王者无关的词里误命中分路，
# 把 OUT_OF_SCOPE 问句抬成 ENTITY_UNKNOWN（走澄清而非拒答）。规格书 4.3 点名要求覆盖的是
# 「上单/中单」这类词，故保留双字形式即可。此约束由 tests/unit/test_intent_routing.py 的
# 「北京到上海多远」用例固化。
LANE_ALIASES = {
    "射手": "发育路", "ad": "发育路", "adc": "发育路", "发育路": "发育路", "下路": "发育路",
    "打野": "打野", "打野位": "打野", "jungle": "打野", "野区": "打野",
    "中单": "中路", "中路": "中路", "法师": "中路", "ap": "中路",
    "辅助": "游走", "游走": "游走", "sup": "游走", "辅助位": "游走", "奶": "游走",
    "上单": "对抗路", "边路": "对抗路", "对抗路": "对抗路", "坦克": "对抗路",
}

# 残句里不算「未识别实体候选」的功能词/疑问词（4.9 的 unrecognized 语义是
# 「疑似实体但没认出来」，若把这类词也算进去，系统会永远走澄清分支）。
STOPWORDS = {
    "怎么", "如何", "咋样", "咋", "什么", "哪个", "哪些", "谁", "是谁", "我", "你", "他",
    "她", "它", "我们", "你们", "他们", "的", "了", "吗", "呢", "吧", "啊", "呀", "嘛",
    "请", "帮", "帮我", "想", "要", "能", "可以", "有没有", "有", "没有", "是", "不是",
    "和", "跟", "与", "及", "还有", "以及", "这个", "那个", "这", "那", "一个", "一下",
    "告诉", "说", "介绍", "推荐", "求", "问", "问一下", "为什么", "为何", "厉害", "强",
    "弱", "值得", "好不好", "克制", "压", "压制", "打", "被", "对线", "对位", "怎么玩",
    "玩法", "打法", "思路", "连招", "意识", "版本", "强度", "上分", "排位", "出装",
    "装备", "铭文", "搭配", "出什么", "技能", "被动", "属性", "攻略", "怎么打", "好不好用",
}

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------- 归一化


def normalize(text: str) -> str:
    """繁简归一 + 全半角归一（NFKC）+ ASCII 大小写归一 + 去空白。

    ASCII 转小写是为分路口语里的英文缩写（AD/ADC/AP/SUP/JUNGLE，规格书 4.3 第 2 级
    点名要求覆盖）——NFKC 只处理全半角，不会把 "AD" 变 "ad"，而 LANE_ALIASES 的键是
    小写，不归一就会漏命中。英雄/装备/铭文名均为中文，转小写不影响它们。
    """
    s = unicodedata.normalize("NFKC", text)
    s = "".join(TRAD_TO_SIMP.get(ch, ch) for ch in s)
    s = s.lower()
    return _WS_RE.sub("", s)


# ---------------------------------------------------------------- 索引


@dataclass(frozen=True)
class _Entry:
    kind: str          # hero / item / inscription / role
    id: str | None
    name: str
    roles: tuple[str, ...] = ()


@dataclass
class _Index:
    entries: dict[str, tuple[_Entry, str]]   # 归一化 key -> (条目, method)
    keys: list[str]                          # 按长度降序（保证最长匹配优先）
    heroes: dict[str, _Entry]                # id -> 英雄条目


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _build_index() -> _Index:
    entries: dict[str, tuple[_Entry, str]] = {}
    heroes: dict[str, _Entry] = {}

    # --- 英雄：规范名 + 别名表（heroes.json 的 aliases 已由 build_graph_data.py 合并
    #     data/hero_aliases.json，这里两者都读并取并集，避免任一侧漏更新） ---
    alias_map: dict[str, list[str]] = {}
    if ALIASES_FILE.exists():
        for row in _load_json(ALIASES_FILE):
            alias_map.setdefault(row["name"], []).extend(row.get("aliases", []))

    for h in _load_json(HEROES_FILE):
        entry = _Entry("hero", h["id"], h["name"], tuple(h.get("roles", [])))
        heroes[h["id"]] = entry
        entries.setdefault(normalize(h["name"]), (entry, "exact"))
        for alias in list(h.get("aliases", [])) + alias_map.get(h["name"], []):
            entries.setdefault(normalize(alias), (entry, "alias"))

    # --- 装备 / 铭文（entity_type 枚举里有这两档，索引上以便 M3 的 ITEM_BUILD / INSCRIPTION 复用） ---
    for path, kind in ((ITEMS_FILE, "item"), (INSCRIPTIONS_FILE, "inscription")):
        if not path.exists():
            continue
        for row in _load_json(path):
            entries.setdefault(normalize(row["name"]), (_Entry(kind, row["id"], row["name"]), "exact"))

    # --- 分路口语 ---
    for alias, lane in LANE_ALIASES.items():
        entries.setdefault(normalize(alias), (_Entry("role", None, lane), "alias"))

    keys = sorted(entries, key=len, reverse=True)
    return _Index(entries, keys, heroes)


@lru_cache(maxsize=1)
def _get_index() -> _Index:
    return _build_index()


# ---------------------------------------------------------------- 扫描（1/2 级）


def _scan(norm: str, index: _Index) -> list[tuple[int, int, _Entry, str]]:
    """最长匹配优先的从左到右扫描，可一次抽出句中多个实体。"""
    out: list[tuple[int, int, _Entry, str]] = []
    i = 0
    n = len(norm)
    while i < n:
        hit = False
        for key in index.keys:
            if key and norm.startswith(key, i):
                entry, method = index.entries[key]
                out.append((i, i + len(key), entry, method))
                i += len(key)
                hit = True
                break
        if not hit:
            i += 1
    return out


# ---------------------------------------------------------------- 模糊匹配（3 级）


@lru_cache(maxsize=4096)
def _pinyin_seq(text: str) -> tuple[str, ...]:
    from pypinyin import Style, lazy_pinyin

    return tuple(lazy_pinyin(text, style=Style.NORMAL))


def _lev(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """音节序列的编辑距离。"""
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[n]


# 编辑距离 -> 置信度。0 距离（同音字）给满分；1 距离仍高于 0.7 阈值；2 距离落到阈值之下被拒。
# 这样「距离 ≤ 2」是必要非充分条件，最终由 ENTITY_CONFIDENCE_THRESHOLD 把关（4.3）。
_FUZZY_CONF = {0: 1.0, 1: 0.8, 2: 0.6}


def _fuzzy(norm: str, index: _Index) -> LinkedEntity | None:
    cand = _pinyin_seq(norm)
    best: tuple[float, _Entry] | None = None
    for key, (entry, _method) in index.entries.items():
        if not key:
            continue
        d = _lev(cand, _pinyin_seq(key))
        if d > 2:
            continue
        conf = _FUZZY_CONF[d]
        if conf < settings.ENTITY_CONFIDENCE_THRESHOLD:
            continue
        if best is None or conf > best[0] or (conf == best[0] and len(key) > len(best[1].name)):
            best = (conf, entry)
    if best is None:
        return None
    conf, entry = best
    return LinkedEntity(
        raw=norm,
        canonical_id=entry.id,
        canonical_name=entry.name,
        entity_type=entry.kind if entry.kind in ("hero", "item", "inscription") else "role",
        confidence=conf,
        method="fuzzy",
    )


# ---------------------------------------------------------------- 未识别残句


def _residuals(norm: str, covered: list[bool]) -> list[str]:
    import jieba

    out: list[str] = []
    for token in jieba.lcut(norm):
        tok = token.strip()
        if not tok or tok in STOPWORDS:
            continue
        if all(not c.isalnum() and not ("\u4e00" <= c <= "\u9fff") for c in tok):
            continue  # 纯标点
        # 该 token 覆盖的字符若已全部被实体命中，则不算未识别
        start = norm.find(tok)
        if start >= 0 and all(covered[start : start + len(tok)]):
            continue
        if len(tok) >= 2 and any("\u4e00" <= c <= "\u9fff" for c in tok):
            out.append(tok)
    return out


# ---------------------------------------------------------------- 对外入口


@dataclass
class LinkingResult:
    entities: list[LinkedEntity]
    unrecognized: list[str]


def _to_entity(raw: str, entry: _Entry, method: str) -> LinkedEntity:
    etype = entry.kind if entry.kind in ("hero", "item", "inscription") else "role"
    return LinkedEntity(
        raw=raw,
        canonical_id=entry.id,
        canonical_name=entry.name,
        entity_type=etype,
        confidence=1.0 if method == "exact" else 0.9,
        method=method,
    )


def link(text: str) -> LinkingResult:
    """把一句用户输入链接为实体列表 + 未识别候选。"""
    norm = normalize(text)
    if not norm:
        return LinkingResult([], [])

    index = _get_index()
    spans = _scan(norm, index)

    covered = [False] * len(norm)
    for start, end, _entry, _method in spans:
        for i in range(start, end):
            covered[i] = True

    entities: list[LinkedEntity] = []
    seen: set[str] = set()
    for start, end, entry, method in spans:
        key = entry.id or entry.name
        if key in seen:
            continue
        seen.add(key)
        entities.append(_to_entity(norm[start:end], entry, method))

    if not entities:
        # 前两级全失败才启用模糊匹配（4.3）；命中则整句视为已覆盖
        fuzzy = _fuzzy(norm, index)
        if fuzzy is not None:
            entities.append(fuzzy)
            covered = [True] * len(norm)

    return LinkingResult(entities, _residuals(norm, covered))


def link_heroes(text: str) -> list[LinkedEntity]:
    """只取英雄类实体（意图路由与模板查询用）。"""
    return [e for e in link(text).entities if e.entity_type == "hero"]
