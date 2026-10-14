"""数据画像：COUNTERS 关系的度数分布（规格书 M1b 要求）。

口径说明（**重要，用于消除方向歧义**）：
官方每个英雄详情页给两段克制关系：
  - `hr2` 压制英雄   = 本英雄压制对方（本英雄是压制者）
  - `hr3` 被压制英雄 = 对方压制本英雄（本英雄是被压制者）
因此图谱中：
  - `COUNTERS` **出边**（`from_id` = 本英雄）= 本英雄压制别人
  - `COUNTERS` **入边**（`to_id`   = 本英雄）= 别人压制本英雄

本脚本按三个层级计数：
  1. **本页正向**：本英雄自己页面上的 hr2 / hr3 条数（官方每页恰各 2 条，恒定）
  2. **反向引用**：本英雄出现在**其他英雄页面**的 hr3 / hr2 区块中的次数
  3. **图谱合计**：COUNTERS 出边总数 / 入边总数（= 正向 + 反向引用）

并列出以下为 0 的英雄清单——这些英雄对应的图谱查询会**必然返回空**，
会触发拒答或降级，是真实的边界情况，属 M6 评测集的重要素材：
  - `hr3 反向引用 = 0`：从未被任何其他英雄的「被压制英雄」区块列为压制者
  - `COUNTERS 入边 = 0`：从未被任何英雄压制（问「XX 被谁克制」必空）
  - `COUNTERS 出边 = 0`：从未压制任何英雄（问「XX 克制谁」必空）

用法：
  python scripts/data_profile.py            # 写 data/data_profile.md 并打印摘要
"""
from __future__ import annotations

import collections
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = PROJECT_ROOT / "data" / "graph"
OUT = PROJECT_ROOT / "data" / "data_profile.md"


def load(name: str):
    return json.loads((GRAPH_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    heroes = load("heroes.json")
    rels = load("relations.json")

    name = {h["id"]: h["name"] for h in heroes}
    url = {h["id"]: h["source"] for h in heroes}

    own_hr2 = collections.Counter(r["from_id"] for r in rels if r["block"] == "hr2")
    own_hr3 = collections.Counter(r["to_id"] for r in rels if r["block"] == "hr3")
    # 反向引用：本英雄出现在"其他英雄页"的区块里
    rev_hr3 = collections.Counter(r["from_id"] for r in rels if r["block"] == "hr3")
    rev_hr2 = collections.Counter(r["to_id"] for r in rels if r["block"] == "hr2")
    out_total = collections.Counter(r["from_id"] for r in rels if r["type"] == "COUNTERS")
    in_total = collections.Counter(r["to_id"] for r in rels if r["type"] == "COUNTERS")

    rows = []
    for h in heroes:
        hid = h["id"]
        rows.append(
            {
                "id": hid,
                "name": h["name"],
                "roles": " / ".join(h["roles"]),
                "hr2_own": own_hr2[hid],
                "hr3_own": own_hr3[hid],
                "hr3_rev": rev_hr3[hid],
                "hr2_rev": rev_hr2[hid],
                "out_total": out_total[hid],
                "in_total": in_total[hid],
            }
        )

    zero_hr3_rev = [r for r in rows if r["hr3_rev"] == 0]
    zero_in = [r for r in rows if r["in_total"] == 0]
    zero_out = [r for r in rows if r["out_total"] == 0]

    by_out = sorted(rows, key=lambda r: (-r["out_total"], r["name"]))
    by_in = sorted(rows, key=lambda r: (-r["in_total"], r["name"]))

    L: list[str] = []
    L.append("# data/data_profile.md — COUNTERS 关系度数画像（M1b）")
    L.append("")
    L.append(f"> 生成日期：{date.today()}　数据源：`data/graph/heroes.json` + `relations.json`")
    L.append("> 本文件由 `scripts/data_profile.py` 生成，勿手工编辑。")
    L.append("")
    L.append("## 口径（消除方向歧义）")
    L.append("")
    L.append("| 官方区块 | 页面含义 | 图谱边方向 |")
    L.append("| --- | --- | --- |")
    L.append("| `hr2` 压制英雄 | 本英雄压制对方 | `本英雄 -[:COUNTERS]-> 对方`（**出边**） |")
    L.append("| `hr3` 被压制英雄 | 对方压制本英雄 | `对方 -[:COUNTERS]-> 本英雄`（**入边**） |")
    L.append("")
    L.append("三层计数：**本页正向**（本英雄自己页面上的条数，官方恒为 2）+ "
             "**反向引用**（本英雄出现在其他英雄页面区块的次数）= **图谱合计**。")
    L.append("")
    L.append("## 汇总")
    L.append("")
    L.append(f"- 英雄数：{len(rows)}；COUNTERS 出边合计 {sum(r['out_total'] for r in rows)}，"
             f"入边合计 {sum(r['in_total'] for r in rows)}（每条边同时是某英雄的出边、另一英雄的入边，两者应相等）")
    L.append(f"- 每英雄本页 hr2 / hr3 恒为 2（官方数据口径，官方每页只给 2 条压制 + 2 条被压制）")
    L.append(f"- **hr3 反向引用 = 0 的英雄：{len(zero_hr3_rev)} 个**")
    L.append(f"- **COUNTERS 入边 = 0 的英雄：{len(zero_in)} 个**")
    L.append(f"- **COUNTERS 出边 = 0 的英雄：{len(zero_out)} 个**")
    L.append("")
    L.append("## 出度 Top 15（本英雄压制别人最多，图谱合计 = 正向 + 反向引用）")
    L.append("")
    L.append("| # | 英雄 | 分路 | 本页 hr2 | 反向引用 hr3 | 出度合计 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(by_out[:15], 1):
        L.append(f"| {i} | {r['name']} | {r['roles']} | {r['hr2_own']} | {r['hr3_rev']} | **{r['out_total']}** |")
    L.append("")
    L.append("## 入度 Top 15（本英雄被压制最多）")
    L.append("")
    L.append("| # | 英雄 | 分路 | 本页 hr3 | 反向引用 hr2 | 入度合计 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(by_in[:15], 1):
        L.append(f"| {i} | {r['name']} | {r['roles']} | {r['hr3_own']} | {r['hr2_rev']} | **{r['in_total']}** |")
    L.append("")
    L.append("## 边界英雄清单（查询必然返回空 → 走拒答/降级）")
    L.append("")
    L.append(f"### hr3 反向引用 = 0（{len(zero_hr3_rev)} 个）——从未被任何其他英雄的「被压制英雄」区块列为压制者")
    L.append("")
    L.append("> 即：官方全量 133 页里，没有一页把该英雄写进自己的 hr3（被压制英雄）区块。")
    L.append("")
    L.append("、".join(r["name"] for r in sorted(zero_hr3_rev, key=lambda x: x["name"])) or "无")
    L.append("")
    L.append(f"### COUNTERS 入边 = 0（{len(zero_in)} 个）——问「XX 被谁克制」图谱必空")
    L.append("")
    L.append("、".join(r["name"] for r in sorted(zero_in, key=lambda x: x["name"])) or "无")
    L.append("")
    L.append(f"### COUNTERS 出边 = 0（{len(zero_out)} 个）——问「XX 克制谁」图谱必空")
    L.append("")
    L.append("、".join(r["name"] for r in sorted(zero_out, key=lambda x: x["name"])) or "无")
    L.append("")
    L.append("## 全量明细")
    L.append("")
    L.append("| 英雄 | 分路 | hr2 本页 | hr3 反向引用 | 出度合计 | hr3 本页 | hr2 反向引用 | 入度合计 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in sorted(rows, key=lambda x: x["name"]):
        L.append(
            f"| {r['name']} | {r['roles']} | {r['hr2_own']} | {r['hr3_rev']} | {r['out_total']} "
            f"| {r['hr3_own']} | {r['hr2_rev']} | {r['in_total']} |"
        )
    L.append("")

    OUT.write_text("\n".join(L), encoding="utf-8")

    print(f"[profile] 已写 {OUT}")
    print(f"[profile] 英雄 {len(rows)}；出边合计 {sum(r['out_total'] for r in rows)}；"
          f"入边合计 {sum(r['in_total'] for r in rows)}")
    print(f"[profile] hr3 反向引用=0：{len(zero_hr3_rev)} 个 -> "
          f"{[r['name'] for r in zero_hr3_rev]}")
    print(f"[profile] 入度=0：{len(zero_in)} 个 -> {[r['name'] for r in zero_in]}")
    print(f"[profile] 出度=0：{len(zero_out)} 个 -> {[r['name'] for r in zero_out]}")
    print(f"[profile] 出度 Top5：{[(r['name'], r['out_total']) for r in by_out[:5]]}")
    print(f"[profile] 入度 Top5：{[(r['name'], r['in_total']) for r in by_in[:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
