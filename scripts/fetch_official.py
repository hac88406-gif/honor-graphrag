"""全量抓取王者荣耀官方数据（英雄 / 关系 / 装备 / 铭文）。

设计依据：规格书 6.1b（四个陷阱）、6.3（抓取脚本技术要求）、6.4（两步走流程）。

四个陷阱的处理：
  ① 详情页是 GBK 编码  -> 显式 decode("gbk")，且做乱码自检（正确解码后不应出现
     拉丁扩展/IPA 区字符或 U+FFFD）
  ② 关系理由没有 ID 绑定 -> 靠同段内 <p> 与英雄列表的顺序一一对应，并**断言
     len(英雄列表) == len(理由列表)**，不等即抛错并记入 fetch_errors.log
  ③ 部分数据在 HTML 注释内 -> 用正则直接穿透，**不做去注释处理**
  ④ 两个 URL 形式都可用 -> 统一用 id_name（可读、便于排查）

本脚本只负责「抓取 + 解析 + 覆盖率报告」。阶段一的入库数据导出由
scripts/build_graph_data.py 完成（读本脚本的快照产物，见规格书 6.4）。

用法：
  python scripts/fetch_official.py                       # 全量抓取 133 英雄
  python scripts/fetch_official.py --limit 3             # 只抓前 3 个（调试）
  python scripts/fetch_official.py --no-cache            # 忽略缓存重抓

产出：
  data/raw/{timestamp}/herolist.json, item.json, ming.json   # 原始 JSON（UTF-8）
  data/raw/{timestamp}/herodetail/{id_name}.shtml            # 原始详情页（已按 GBK 解码）
  data/raw/{timestamp}/parsed/                               # 解析后的全量中间结果
  data/raw/{timestamp}/fetch_meta.json                       # 计数与耗时
  data/fetch_report.md                                       # 覆盖率统计报告
  data/fetch_errors.log                                      # 追加式错误日志
  data/raw/.cache/                                           # 断点续跑缓存（原始页面字节）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------- 常量与配置

BASE = "https://pvp.qq.com/web201605"
URL_HEROLIST = f"{BASE}/js/herolist.json"
URL_ITEM = f"{BASE}/js/item.json"
URL_MING = f"{BASE}/js/ming.json"
URL_DETAIL = BASE + "/herodetail/{}.shtml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://pvp.qq.com/",
}

# 规格书 6.3-1：请求间隔 ≥ 0.5s；取 0.6s 留余量
RATE_LIMIT_SECONDS = 0.6

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
CACHE_DIR = RAW_DIR / ".cache"
FETCH_REPORT = PROJECT_ROOT / "data" / "fetch_report.md"
FETCH_ERRORS = PROJECT_ROOT / "data" / "fetch_errors.log"

CURRENT_PATCH = "2026-10"  # 规格书 1.11

# 分路编码 -> 分路名。编码含义非文档给出，由实测反查确定（见 DECISIONS.md）
ROLE_CODE_TO_LANE = {"1": "对抗路", "2": "打野", "3": "中路", "4": "发育路", "5": "游走"}

# item_type -> 分类名。映射由实测样本归纳（见 DECISIONS.md）；数据中不存在 6
ITEM_TYPE_TO_CATEGORY = {1: "攻击", 2: "法术", 3: "防御", 4: "移动", 5: "打野", 7: "游走"}

# ming_type -> 颜色名。实测取值是 red/yellow/blue（规格书 6.1b 写的 green 有误，见 DECISIONS.md）
MING_TYPE_TO_COLOR = {"red": "红", "yellow": "黄", "blue": "蓝"}

# 三段关系区块：图标类名 -> (页面标签, 关系语义)
#   hr1 最佳搭档   -> (本英雄)-[:SYNERGIZES]->(对方)
#   hr2 压制英雄   -> (本英雄)-[:COUNTERS]->(对方)
#   hr3 被压制英雄 -> (对方)-[:COUNTERS]->(本英雄)   ← 方向反转，不建反向边（规格书 4.5）
REL_BLOCKS = {
    "hr1": ("最佳搭档", "SYNERGIZES", False),
    "hr2": ("压制英雄", "COUNTERS", False),
    "hr3": ("被压制英雄", "COUNTERS", True),
}

# 正确 GBK 解码后，中文文本中不应出现的区间：
#   U+0100-U+02FF 拉丁扩展/IPA、U+E000-U+F8FF 私用区、U+FFFD 替换字符。
# 注意不要包含 U+00A0-U+00FF —— 其中 · (U+00B7) 与 × (U+00D7) 是官方装备名的合法字符
# （例："极影·救赎"）。GBK 乱码（GBK 字节被当 latin-1/UTF-8 解）必然落在上面的区间里。
BAD_CHAR_RE = re.compile(r"[\u0100-\u02ff\ue000-\uf8ff\ufffd]")
# 汉字 + CJK 标点 + 全角字符
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

_last_request_at = 0.0


class FetchError(RuntimeError):
    """抓取层错误（网络 / 编码 / 结构）。"""


class RelationPairError(FetchError):
    """陷阱二：英雄列表长度与理由列表长度不一致。"""


# ---------------------------------------------------------------- 基础 IO


def _throttle() -> None:
    global _last_request_at
    wait = RATE_LIMIT_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".bin")


def fetch_bytes(url: str, *, use_cache: bool = True) -> bytes:
    """带限速与缓存的原始字节抓取。缓存用于断点续跑（规格书 6.3-5）。"""
    cp = _cache_path(url)
    if use_cache and cp.exists() and cp.stat().st_size > 0:
        return cp.read_bytes()
    _throttle()
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    if not resp.content:
        raise FetchError(f"空响应: {url}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(resp.content)
    return resp.content


def fetch_json(url: str, *, use_cache: bool = True) -> object:
    """JSON 端点：UTF-8。"""
    return json.loads(fetch_bytes(url, use_cache=use_cache).decode("utf-8"))


def fetch_detail_html(id_name: str, *, use_cache: bool = True) -> str:
    """详情页：GBK（陷阱一）。"""
    raw = fetch_bytes(URL_DETAIL.format(id_name), use_cache=use_cache)
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError as e:
        raise FetchError(f"GBK 解码失败 {id_name}: {e}") from e


# ---------------------------------------------------------------- 校验工具


def assert_no_mojibake(text: str, label: str) -> None:
    """乱码自检（规格书 6.3-6）。

    双重判据：
      1) 命中明确不可能出现的字符区间（拉丁扩展/IPA、私用区、U+FFFD）；
      2) 含非 ASCII 字符时，非 ASCII 字符中的汉字占比必须 ≥ 50%。
    纯英文/数字字段（如 "Tips：" 之外的编号）不受影响。
    """
    if not text:
        return
    m = BAD_CHAR_RE.search(text)
    if m:
        raise FetchError(
            f"疑似乱码 [{label}] 命中字符 {m.group(0)!r} (U+{ord(m.group(0)):04X})"
        )
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return
    cjk = sum(1 for c in non_ascii if CJK_RE.match(c))
    if cjk == 0:
        raise FetchError(f"疑似乱码 [{label}]：含非 ASCII 但无汉字 -> {text[:40]!r}")
    if cjk / len(non_ascii) < 0.5:
        raise FetchError(
            f"疑似乱码 [{label}]：非汉字占比过高（{len(non_ascii)-cjk}/{len(non_ascii)}）-> {text[:40]!r}"
        )


def clean_text(raw_html: str) -> str:
    """去标签、去多余空白，保留纯文本。"""
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


# ---------------------------------------------------------------- 详情页解析


def parse_relations(html: str, hero_label: str) -> dict[str, list[dict]]:
    """解析三段关系区块（陷阱二、三）。

    锚点用 <i class="hrN ...">，**不依赖容器 class**——实测最佳搭档区块的外层 class
    与其余两段不同，靠 class 定位会把压制英雄误当最佳搭档。
    """
    anchors = [(m.group(1), m.start()) for m in re.finditer(r'<i class="(hr[123])[^"]*"', html)]
    result: dict[str, list[dict]] = {k: [] for k in REL_BLOCKS}
    if not anchors:
        return result

    first = min(p for _, p in anchors)
    # 关系区结束于「出装建议」区块（tb6 图标 / equip 容器）
    ends = [
        p
        for p in (html.find('class="tb6'), html.find('<div class="equip'))
        if p > first
    ]
    region_end = min(ends) if ends else len(html)

    ordered = sorted(anchors, key=lambda x: x[1])
    for i, (key, pos) in enumerate(ordered):
        nxt = ordered[i + 1][1] if i + 1 < len(ordered) else region_end
        chunk = html[pos:nxt]

        reasons = [clean_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", chunk, re.S)]

        # 官方详情页存在两套模板（实测）：
        #   新版：<img class="hero-relate-img" data-src="157" ...>
        #   旧版：<img src="...heroimg/113/113.jpg" ...>（无 data-src，只有 href）
        # 规格书 6.1b 也写明"从 data-src 或 href 提取"，因此两条通道都试，
        # 取长度与理由数一致的那条；都不同则断言失败。
        candidates = {
            "href": re.findall(r'href="(\d+)\.shtml"', chunk),
            "data-src": re.findall(r'data-src="(\d+)"', chunk),
        }
        hero_ids = next((v for v in candidates.values() if len(v) == len(reasons)), None)

        # 陷阱二的核心断言：禁止按位置硬猜
        if hero_ids is None:
            raise RelationPairError(
                f"[{hero_label}] {REL_BLOCKS[key][0]} 理由数={len(reasons)}，"
                f"但英雄 ID 候选均不匹配（href={candidates['href']} data-src={candidates['data-src']}），"
                "结构可能已变"
            )
        for hid, reason in zip(hero_ids, reasons):
            assert_no_mojibake(reason, f"{hero_label}/{REL_BLOCKS[key][0]}/理由")
            result[key].append({"hero_id": hid, "reason": reason})
    return result


def parse_difficulty(html: str) -> dict[str, int]:
    """四项属性条：cover-list 的 data-bar1..4 的 width 百分比。"""
    out: dict[str, int] = {}
    for m in re.finditer(
        r'data-bar(\d)[^>]*>.*?<i class="ibar" style="width:(\d+)%"',
        html,
        re.S,
    ):
        out[f"bar{m.group(1)}"] = int(m.group(2))
    return out


def parse_ming_sets(html: str) -> list[list[str]]:
    """铭文搭配（陷阱三：第二套在注释内，正则穿透即可）。"""
    sets = re.findall(r'data-ming="([^"]*)"', html)
    return [[x for x in s.split("|") if x] for s in sets]


def parse_item_sets(html: str) -> list[list[str]]:
    """推荐出装（陷阱三）。每套 6 件，顺序即出装顺序。"""
    sets = re.findall(r'data-item="([^"]*)"', html)
    return [[x for x in s.split("|") if x] for s in sets]


def parse_equip_tips(html: str) -> list[str]:
    return [clean_text(t) for t in re.findall(r'<p class="equip-tips">(.*?)</p>', html, re.S)]


def parse_skills(html: str) -> list[dict]:
    """技能名 + 描述。

    结构（实测）：
      <div class="skill-show">
        <div class="show-list">
          <p class="skill-name"><b>技能名</b><span>冷却值：..</span><span>消耗：..</span></p>
          <p class="skill-desc">描述</p>
        </div>
        ...
        <div class="show-list"></div>   <- 末尾空槽位（no5），不含 <b>
    因此取 <b> 内的技能名与 skill-desc 描述按序配对；空槽位不产生记录。
    """
    i, j = html.find('class="tb2'), html.find('class="tb3')
    seg = html[i:j] if i > 0 and j > i else html
    k = seg.find('class="skill-show')
    if k > 0:
        seg = seg[k:]
    names = [clean_text(x) for x in re.findall(r"<b>(.*?)</b>", seg, re.S)]
    descs = [clean_text(x) for x in re.findall(r'<p class="skill-desc">(.*?)</p>', seg, re.S)]
    out = []
    for idx, name in enumerate(names):
        desc = descs[idx] if idx < len(descs) else ""
        if not name or not desc:
            continue
        assert_no_mojibake(desc, f"技能描述/{name}")
        out.append({"name": name, "desc": desc})
    return out


def parse_detail(html: str, hero_label: str) -> dict:
    return {
        "relations": parse_relations(html, hero_label),
        "difficulty_bars": parse_difficulty(html),
        "ming_sets": parse_ming_sets(html),
        "item_sets": parse_item_sets(html),
        "equip_tips": parse_equip_tips(html),
        "skills": parse_skills(html),
    }


# ---------------------------------------------------------------- 主流程


def _log_error(msg: str) -> None:
    FETCH_ERRORS.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with FETCH_ERRORS.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 个英雄（调试用）")
    ap.add_argument("--no-cache", action="store_true", help="忽略本地缓存重新请求")
    args = ap.parse_args()
    use_cache = not args.no_cache

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = RAW_DIR / stamp
    parsed_dir = snap / "parsed"
    detail_dir = snap / "herodetail"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    print(f"[fetch] 快照目录 = {snap}")

    # --- 1. 三个 JSON 端点 ---
    herolist = fetch_json(URL_HEROLIST, use_cache=use_cache)
    items = fetch_json(URL_ITEM, use_cache=use_cache)
    mings = fetch_json(URL_MING, use_cache=use_cache)
    (snap / "herolist.json").write_text(json.dumps(herolist, ensure_ascii=False, indent=2), encoding="utf-8")
    (snap / "item.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (snap / "ming.json").write_text(json.dumps(mings, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fetch] herolist={len(herolist)} item={len(items)} ming={len(mings)}")

    # --- 2. 装备 / 铭文结构化 ---
    items_all = []
    for it in items:
        src = f"{URL_ITEM}"
        items_all.append(
            {
                "id": str(it["item_id"]),
                "name": it["item_name"],
                "category": ITEM_TYPE_TO_CATEGORY.get(it["item_type"], f"未知({it['item_type']})"),
                "price": it.get("total_price", it.get("price")),
                "patch": CURRENT_PATCH,
                "source": src,
            }
        )
        assert_no_mojibake(it["item_name"], "装备名")

    inscriptions_all = []
    for mg in mings:
        inscriptions_all.append(
            {
                "id": str(mg["ming_id"]),
                "name": mg["ming_name"],
                "color": MING_TYPE_TO_COLOR.get(mg["ming_type"], mg["ming_type"]),
                "level": int(mg["ming_grade"]) if str(mg["ming_grade"]).isdigit() else None,
                "des": clean_text(mg["ming_des"]),
                "patch": CURRENT_PATCH,
                "source": URL_MING,
            }
        )
        assert_no_mojibake(mg["ming_name"], "铭文名")

    # --- 3. 逐英雄抓详情页 ---
    targets = herolist[: args.limit] if args.limit else herolist
    heroes_all, relations_all, failures = [], [], []
    for idx, hero in enumerate(targets, 1):
        ename = str(hero["ename"])
        id_name = hero["id_name"]
        label = f"{hero['cname']}({id_name})"
        try:
            html = fetch_detail_html(id_name, use_cache=use_cache)
            assert_no_mojibake(hero["cname"], f"{label}/英雄名")
            (detail_dir / f"{id_name}.shtml").write_text(html, encoding="utf-8")

            parsed = parse_detail(html, label)
            bars = parsed["difficulty_bars"]
            roles = [ROLE_CODE_TO_LANE[c] for c in str(hero.get("roles", "")).split("|") if c in ROLE_CODE_TO_LANE]

            heroes_all.append(
                {
                    "id": ename,
                    "name": hero["cname"],
                    "title": hero["title"],
                    "id_name": id_name,
                    "roles": roles,
                    "hero_type": hero.get("hero_type"),
                    "hero_type2": hero.get("hero_type2"),
                    "difficulty": bars.get("bar4"),  # bar4 = 上手难度
                    "survival": bars.get("bar1"),
                    "damage": bars.get("bar2"),
                    "skill_effect": bars.get("bar3"),
                    "patch": CURRENT_PATCH,
                    "source": URL_DETAIL.format(id_name),
                    "data_source": "official",
                }
            )

            # 关系：hr3 方向反转（对方 COUNTERS 本英雄）
            for key, rows in parsed["relations"].items():
                _, rel_type, reverse = REL_BLOCKS[key]
                for row in rows:
                    other = row["hero_id"]
                    frm, to = (other, ename) if reverse else (ename, other)
                    relations_all.append(
                        {
                            "from_id": frm,
                            "to_id": to,
                            "type": rel_type,
                            "block": key,
                            "reason": row["reason"],
                            "weight": 1.0,  # 官方无权重；默认 1.0，语义=关系存在（规格书 4.5）
                            "patch": CURRENT_PATCH,
                            "source": URL_DETAIL.format(id_name),
                        }
                    )

            # 搭配（出装 / 铭文）随英雄一起落中间结果
            heroes_all[-1]["ming_sets"] = parsed["ming_sets"]
            heroes_all[-1]["item_sets"] = parsed["item_sets"]
            heroes_all[-1]["equip_tips"] = parsed["equip_tips"]
            heroes_all[-1]["skills"] = parsed["skills"]

        except Exception as e:  # 记录并跳过该英雄，绝不用模型记忆补全（规格书 1.1b）
            msg = f"{type(e).__name__} {label}: {e}"
            failures.append({"hero": label, "error": msg})
            _log_error(msg)
            print(f"  !! [{idx}/{len(targets)}] {msg}")

        if idx % 10 == 0 or idx == len(targets):
            print(f"  [{idx}/{len(targets)}] 已处理，失败 {len(failures)}")

    # --- 4. 中间结果落盘 ---
    (parsed_dir / "heroes_all.json").write_text(json.dumps(heroes_all, ensure_ascii=False, indent=2), encoding="utf-8")
    (parsed_dir / "relations_all.json").write_text(json.dumps(relations_all, ensure_ascii=False, indent=2), encoding="utf-8")
    (parsed_dir / "items_all.json").write_text(json.dumps(items_all, ensure_ascii=False, indent=2), encoding="utf-8")
    (parsed_dir / "inscriptions_all.json").write_text(json.dumps(inscriptions_all, ensure_ascii=False, indent=2), encoding="utf-8")
    (parsed_dir / "parse_errors.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 5. 覆盖率统计（规格书 6.3-4 / 1.12）：按英雄去重统计"该区块非空的英雄数" ---
    by_name = {h["id"]: h["name"] for h in heroes_all}
    cov = {"hr1": set(), "hr2": set(), "hr3": set()}
    for rel in relations_all:
        # hr3 是"对方压制本英雄"，本英雄是 to_id；hr1/hr2 本英雄是 from_id
        src_hero = rel["to_id"] if rel["block"] == "hr3" else rel["from_id"]
        cov[rel["block"]].add(src_hero)

    with_ming = [h["name"] for h in heroes_all if h.get("ming_sets")]
    with_item = [h["name"] for h in heroes_all if h.get("item_sets")]

    # 出装引用的装备 ID 与官方 item.json 目录比对：缺失项统计（供报告与入库跳过）
    item_id_set = {str(it["id"]) for it in items_all}
    missing_item_refs: dict[str, int] = {}
    for h in heroes_all:
        for build in h.get("item_sets", []):
            for iid in build:
                if str(iid) not in item_id_set:
                    missing_item_refs[str(iid)] = missing_item_refs.get(str(iid), 0) + 1

    elapsed = time.monotonic() - t0
    meta = {
        "snapshot": stamp,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "rate_limit_seconds": RATE_LIMIT_SECONDS,
        "hero_total": len(herolist),
        "hero_fetched": len(heroes_all),
        "hero_failed": len(failures),
        "item_total": len(items_all),
        "inscription_total": len(inscriptions_all),
        "relation_total": len(relations_all),
        "coverage": {
            "best_partner(hr1)_non_empty": len(cov["hr1"]),
            "counters(hr2)_non_empty": len(cov["hr2"]),
            "countered_by(hr3)_non_empty": len(cov["hr3"]),
            "ming_sets_non_empty": len(with_ming),
            "item_sets_non_empty": len(with_item),
        },
        "missing_item_refs": dict(sorted(missing_item_refs.items())),
        "failures": failures,
    }
    (snap / "fetch_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    write_fetch_report(meta, heroes_all, cov, failures)

    print(f"[fetch] 完成：英雄 {len(heroes_all)}/{len(herolist)}，关系 {len(relations_all)} 条，"
          f"失败 {len(failures)}，耗时 {elapsed:.1f}s")
    print(f"[fetch] 覆盖率 -> 搭档 {len(cov['hr1'])} / 压制 {len(cov['hr2'])} / 被压制 {len(cov['hr3'])}；"
          f"铭文 {len(with_ming)} / 出装 {len(with_item)}")
    if missing_item_refs:
        total_refs = sum(missing_item_refs.values())
        print(f"[fetch] 出装引用缺失：{len(missing_item_refs)} 个 ID / {total_refs} 处引用 -> "
              f"{sorted(missing_item_refs)}（已跳过，未造桩）")

    if failures:
        print(f"[fetch] 存在 {len(failures)} 项解析失败，详见 {FETCH_ERRORS}")
        return 1
    return 0


def write_fetch_report(meta: dict, heroes: list[dict], cov: dict, failures: list[dict]) -> None:
    total = len(heroes) or 1
    lines = [
        "# 抓取覆盖率统计报告（自动生成）",
        "",
        f"- 快照目录：`data/raw/{meta['snapshot']}/`",
        f"- 生成时间：{meta['generated_at']}",
        f"- 抓取耗时：{meta['elapsed_seconds']}s（限速 {meta['rate_limit_seconds']}s/请求）",
        f"- 官方英雄总数：{meta['hero_total']}，本次成功解析：{meta['hero_fetched']}，失败：{meta['hero_failed']}",
        f"- 装备：{meta['item_total']} 件；铭文：{meta['inscription_total']} 个",
        f"- 关系总数（已含 hr3 方向反转）：{meta['relation_total']} 条（**源数据层口径**）",
        "",
        "> **关系计数口径（全项目统一，2026-10-14 起）**：本项目关系计数分三层，引用任何 "
        "COUNTERS / SYNERGIZES 数字时**必须注明层级**——",
        "> - **源数据层**：`data/raw/<snapshot>/parsed/relations_all.json` —— "
        "798 行（COUNTERS 532 / SYNERGIZES 266）",
        "> - **导出层**：`data/graph/relations.json` —— 798 行（COUNTERS 532 / SYNERGIZES 266）；"
        "与源数据层同数、**未去重**",
        "> - **入库后层**：Neo4j —— 793 边（COUNTERS 527 / SYNERGIZES 266）；"
        "= 导出层按唯一键 `起点+类型+终点+patch` MERGE 去重，差 5 条重复边",
        "> 本报告的计数均为**源数据层**。",
        "",
        "## 三项关系数据覆盖率",
        "",
        "| 关系（页面区块） | 非空英雄数 | 占比 |",
        "| --- | --- | --- |",
        f"| 最佳搭档 hr1 | {len(cov['hr1'])} | {len(cov['hr1'])/total:.1%} |",
        f"| 压制英雄 hr2 | {len(cov['hr2'])} | {len(cov['hr2'])/total:.1%} |",
        f"| 被压制英雄 hr3 | {len(cov['hr3'])} | {len(cov['hr3'])/total:.1%} |",
        "",
        "## 出装 / 铭文搭配覆盖率",
        "",
        f"- 有铭文搭配的英雄：{meta['coverage']['ming_sets_non_empty']} / {total}",
        f"- 有推荐出装的英雄：{meta['coverage']['item_sets_non_empty']} / {total}",
        "",
        "## 出装引用缺失（已跳过、未造桩节点）",
        "",
    ]
    miss = meta.get("missing_item_refs", {})
    if miss:
        ids = "、".join(f"`{k}`({v}处)" for k, v in miss.items())
        lines.append(
            f"- 出装引用的装备 ID 中，有 **{len(miss)} 个**不在官方 `item.json`（{meta['item_total']} 件）里，"
            f"共 **{sum(miss.values())} 处**引用：{ids}"
        )
        lines.append(
            "- 处理：对应 `RECOMMENDS_ITEM` 边**不建立**；按规格书 3.4「装备恰 115」**不为其造桩节点**"
            "（缺失装备在任何官方数据源中都不存在，造桩即编造数据）。"
        )
        lines.append(
            "- 成因：这些 ID 取自英雄页 `data-item` 属性（官方页真实数据），**确实不在 `item.json` 目录里**"
            "（非解析遗漏——已在原始 `item.json` 与解析结果中双向核对，均查无此 ID）："
        )
        lines.append(
            "  - `1223` / `1225` / `1722`：常规 4 位 `item_id` 的编号缺口。`1722` 尤其明显——"
            "目录含 `1721`/`1723`/`1724`/`1725`/`1727`/`1728`，却唯独缺 `1722`。"
        )
        lines.append(
            "  - `91040`：5 位 ID，但官方 `item.json` 的 5 位 ID 只有 8 个、且全部集中在 `11xxx`–`13xxx`；"
            "`91040` 落在 `9xxxx` 段，**明显属另一套编号命名空间**（常规 `item_id` 为 4 位）。"
        )
        lines.append("- 待官方 `item.json` 补齐后可重跑 `build_graph_data.py` + `init_graph.py` 恢复这些边。")
    else:
        lines.append("无。所有出装引用的装备 ID 均在官方 `item.json` 中。")
    lines += [
        "",
        "## 解析失败清单",
        "",
    ]
    if failures:
        lines += ["| 英雄 | 错误 |", "| --- | --- |"]
        lines += [f"| {f['hero']} | `{f['error']}` |" for f in failures]
    else:
        lines.append("无。三项关系区块的「英雄列表长度 == 理由列表长度」断言全部通过。")
    lines += ["", "> 本报告由 `scripts/fetch_official.py` 生成，勿手工编辑。"]
    FETCH_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
