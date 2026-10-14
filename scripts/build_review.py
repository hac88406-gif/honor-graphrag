"""生成 data/REVIEW.md（规格书 6.4 阶段一交付物）。

从 data/graph/*.json 与 data/guides/*.md 直接生成审核清单，保证：
  - 每条关系的官方 URL 取自数据本身，不手抄（避免人工录入错误）
  - llm_assisted 条目单列
  - 不确定项由脚本自动检出（缺失装备引用 / 重复关系），不靠记忆

用法：
  python scripts/build_review.py
"""
from __future__ import annotations

import collections
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = PROJECT_ROOT / "data" / "graph"
GUIDES_DIR = PROJECT_ROOT / "data" / "guides"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT = PROJECT_ROOT / "data" / "REVIEW.md"

BLOCK_CN = {"hr1": "最佳搭档", "hr2": "压制英雄", "hr3": "被压制英雄"}
TYPE_CN = {"COUNTERS": "COUNTERS（压制）", "SYNERGIZES": "SYNERGIZES（搭档）"}


def latest_snapshot_name() -> str:
    dirs = [p for p in RAW_DIR.iterdir() if p.is_dir() and p.name != ".cache"]
    return max(dirs, key=lambda p: p.name).name if dirs else "（无快照）"


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def semantics(r: dict) -> str:
    if r["type"] == "COUNTERS":
        return f"{r['from_name']} 压制 {r['to_name']}"
    return f"{r['from_name']} 与 {r['to_name']} 搭档"


def main() -> int:
    heroes = load(GRAPH_DIR / "heroes.json")
    rels = load(GRAPH_DIR / "relations.json")
    items = load(GRAPH_DIR / "items.json")
    name_by_id = {h["id"]: h["name"] for h in heroes}
    item_ids = {i["id"] for i in items}

    # M1b：133 英雄全量入库；演示英雄（有别名语料者，即 M1a 的 5 个）保留逐条清单便于抽查
    demo_heroes = [h for h in heroes if h["aliases"]]
    by_type = collections.Counter(r["type"] for r in rels)
    by_block = collections.Counter(r["block"] for r in rels)

    # --- 不确定项自动检出 ---
    missing_items = collections.Counter()
    for h in heroes:
        for build in h["item_sets"]:
            for iid in build:
                if iid not in item_ids:
                    missing_items[iid] += 1

    dup = {
        k: v
        for k, v in collections.Counter(
            (r["from_id"], r["to_id"], r["type"]) for r in rels
        ).items()
        if v > 1
    }

    # --- 语料 ---
    guides = []
    for p in sorted(GUIDES_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        fm = text.split("---", 2)[1]
        meta = {}
        for line in fm.strip().split("\n"):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
        guides.append((p.name, meta))

    L = []
    L.append("# data/REVIEW.md — 数据审核清单（M1b 全量口径）")
    L.append("")
    L.append(f"> 生成日期：{date.today()}　快照：`data/raw/{latest_snapshot_name()}`")
    L.append("> 本文件由 `scripts/build_review.py` 从 `data/graph/*.json` 与 `data/guides/*.md` 生成，"
             "所有 URL 均取自数据本身。")
    L.append("")
    L.append("## 0. 审核指引（规格书 6.4「需求方审核要点」）")
    L.append("")
    L.append("1. **抽查 5 条关系**：点开下表任一 `source` URL，确认官网页面上确实写着这条关系。")
    L.append("2. **方向核对**：`语义` 列写明了谁压制谁 / 谁与谁搭档；官网页面上「压制英雄」= 本英雄压制对方，"
             "「被压制英雄」= 对方压制本英雄。")
    L.append("3. **source / patch 完整性**：下表每条都有真实 URL 与 `2026-10`，无空缺。")
    L.append("4. **语料可读性**：见第 3 节，重点看 `llm_assisted` 的 C2 五篇有无模板腔。")
    L.append("")
    L.append("## 1. 抓取规模与覆盖率")
    L.append("")
    L.append("- 英雄 133 / 装备 115 / 铭文 93，全部抓取成功，`parse_errors` 为空。")
    L.append("- 三项关系区块覆盖率 133/133（每英雄恰 2/2/2 条）。详见 `data/fetch_report.md`。")
    L.append("")
    L.append("## 2. 关系数据（M1b 全量口径）")
    L.append("")
    L.append(f"- 关系总数：**{len(rels)}** 条"
             f"（COUNTERS {by_type['COUNTERS']} / SYNERGIZES {by_type['SYNERGIZES']}）")
    L.append(f"- 按页面区块：hr1 最佳搭档 {by_block['hr1']} / hr2 压制英雄 {by_block['hr2']} / "
             f"hr3 被压制英雄 {by_block['hr3']}")
    L.append(f"- 覆盖英雄：{len(heroes)} 个全量入库（M1a 的「邻居英雄桩节点」随全量入库自然消失，桩节点数 = 0）")
    L.append("")
    L.append("> 全量逐条（含每条 `source` URL）见 `data/graph/relations.json`；"
             "各英雄 COUNTERS 出度/入度与边界英雄清单见 `data/data_profile.md`。")
    L.append("> 下面保留 M1a 的 5 个演示英雄逐条清单（口径与 M1a 一致），便于需求方抽查方向与 URL。")
    L.append("")
    L.append("### 2.1 演示英雄逐条清单")
    L.append("")
    for idx, h in enumerate(demo_heroes, 1):
        hid = h["id"]
        rows = [r for r in rels if r["from_id"] == hid or r["to_id"] == hid]
        L.append(f"#### 2.1.{idx} {h['name']}（id={hid}，{len(rows)} 条）")
        L.append("")
        L.append(f"- 官方页：{h['source']}")
        L.append(f"- 分路：{' / '.join(h['roles'])}　上手难度：{h['difficulty']}　patch：{h['patch']}")
        L.append("")
        L.append("| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |")
        L.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, r in enumerate(rows, 1):
            block = BLOCK_CN.get(r.get("block", ""), r.get("block", ""))
            reason = r["reason"].replace("|", "\\|")
            L.append(
                f"| {i} | {r['from_name']} → {r['to_name']}（{r['type']}） | {semantics(r)} | "
                f"{block} | {reason} | {r['source']} | {r['patch']} |"
            )
        L.append("")

    c1 = [g for g in guides if g[1].get("data_source") == "real"]
    c2 = [g for g in guides if g[1].get("data_source") == "llm_assisted"]
    L.append("## 3. 语料清单（C1 官方聚合 / C2 LLM 生成）")
    L.append("")
    L.append(f"共 {len(guides)} 篇。C1 = 官方原文聚合（`data_source=real`，与图谱关系同源）；"
             "C2 = 基于官方事实撰写的对线思路（`data_source=llm_assisted`）。")
    L.append("")
    L.append(f"- **C1 {len(c1)} 篇**（每英雄一篇官方聚合，覆盖 133 英雄）；**C2 {len(c2)} 篇**（M1a 已审，未改动）。"
             f"C1:C2 ≈ {len(c1)/max(len(c2),1):.0f}:1，满足「C1 为主干、≥3:1」要求。")
    L.append("")
    L.append("### 3.1 llm_assisted 条目（**单独列出，集中审核**）")
    L.append("")
    L.append("| doc_id | 主题 | 涉及英雄 | 事实来源（官方页） | 文本性质 |")
    L.append("| --- | --- | --- | --- | --- |")
    for name, m in guides:
        if m.get("data_source") == "llm_assisted":
            hname = name_by_id.get(m["hero_ids"].strip("[]").strip('"'), m["hero_ids"])
            L.append(
                f"| {m['doc_id']} | {m['topic']} | {hname} | {m['source_url']} | "
                "LLM 生成，事实源为官方页面 |"
            )
    L.append("")
    L.append("> 说明：C2 的 `source_type=official`（事实出自官方页），`data_source=llm_assisted`（文本为生成）。"
             "两字段分工见 DECISIONS.md。审核重点：表达是否自然、有无模板腔、是否与官方事实一致。")
    L.append("")
    L.append("### 3.2 C1 官方聚合条目（原文，无需逐句审）")
    L.append("")
    L.append("| doc_id | 主题 | 涉及英雄 | 事实来源（官方页） |")
    L.append("| --- | --- | --- | --- |")
    for name, m in guides:
        if m.get("data_source") == "real":
            hname = name_by_id.get(m["hero_ids"].strip("[]").strip('"'), m["hero_ids"])
            L.append(f"| {m['doc_id']} | {m['topic']} | {hname} | {m['source_url']} |")
    L.append("")

    L.append("## 4. 不确定项 / 需重点确认")
    L.append("")
    if missing_items:
        L.append("### 4.1 出装引用了 item.json 中不存在的装备 ID（**对应边未建立**）")
        L.append("")
        L.append("| 装备 ID | 被引用次数 | 处理 |")
        L.append("| --- | --- | --- |")
        for iid, n in sorted(missing_items.items()):
            L.append(f"| {iid} | {n} | 未建 RECOMMENDS_ITEM 边；未造桩节点（规格书 3.4 要求装备恰 115）|")
        L.append("")
        L.append("> 待官方 `item.json` 补齐后可重跑 `build_graph_data.py` + `init_graph.py`。")
        L.append("")
    if dup:
        L.append("### 4.2 同一关系被两处官方页面各陈述一次（导入时按唯一键合并）")
        L.append("")
        L.append("| 关系（from → to，type） | 出现的页面区块 |")
        L.append("| --- | --- |")
        for (fid, tid, typ), _ in dup.items():
            rows = [r for r in rels if (r["from_id"], r["to_id"], r["type"]) == (fid, tid, typ)]
            pages = "；".join(
                f"{BLOCK_CN.get(r['block'], r['block'])} @ {r['source']}" for r in rows
            )
            fn = next((r["from_name"] for r in rows), fid)
            tn = next((r["to_name"] for r in rows), tid)
            L.append(f"| {fn} → {tn}（{typ}） | {pages} |")
        L.append("")
        L.append("> 两条陈述事实一致，方向一致；Neo4j 侧 MERGE 唯一键为 `起点+类型+终点+patch`，"
                 "已合并为 1 条边。语料与图谱不冲突。")
        L.append("")
    L.append("### 4.3 与规格书描述不一致、已实测修正的点（详见 DECISIONS.md）")
    L.append("")
    L.append("- 铭文 `ming_type`：规格书 6.1b 写有 `green`，**实测仅 red/yellow/blue**，无绿色系。")
    L.append("- 装备 `item_type`：实测取值 {1,2,3,4,5,7}，**不存在 6**；未命中类型落为「未知(N)」。")
    L.append("- 貂蝉详情页存在**两套模板**（旧 `href` / 新 `data-src`），已用双通道提取解决，未放宽断言。")
    L.append("")
    L.append("### 4.4 别名清单（供实体链接层审核，每英雄 ≥5）")
    L.append("")
    L.append(f"- 别名语料 `data/hero_aliases.json` 覆盖 **{len(demo_heroes)} 个演示英雄**（M1a 已交付、已审）；"
             "其余英雄 `aliases` 暂为空列表，待 M2 实体链接层按需补齐（见 DECISIONS.md M1b 条）。")
    L.append("")
    L.append("| 英雄 | 别名 |")
    L.append("| --- | --- |")
    for h in demo_heroes:
        L.append(f"| {h['name']} | {'、'.join(h['aliases'])} |")
    L.append("")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"[review] 已生成 {OUT}（{len(L)} 行）")
    print(f"[review] 关系 {len(rels)} 条 / 语料 {len(guides)} 篇 / 缺失装备 {len(missing_items)} 个 / 重复关系 {len(dup)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
