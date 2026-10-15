"""生成语料中的 C1 部分（官方文本聚合，规格书 6.2 来源 C1）。

C1 = 官方详情页的「克制/搭档理由 + 技能描述 + 铭文说明 + 出装说明」按英雄聚合。
文本全部取自抓取快照（官方原文），不经过任何改写——这样语料与图谱关系同源，
天然一致（规格书 6.2 强调的架构优势）。

M1a 只为 5 个样例英雄生成；**M1b 为全量 133 英雄各生成一篇**（规格书 M1b 语料 ≥100）。

C2（LLM 生成的对线思路）不由此脚本产出：它是人工/模型撰写的内容，单独放
data/guides/c2-*.md，本脚本只写 c1-*.md，不触碰 c2-*.md。

**C1 是派生数据，不入版本库**（需求方 2026-10-15 裁定 C1）：它与同样被 gitignore 的
`data/raw/` 同性质（都是抓取/解析产物），故改为加 `.gitignore`、由本脚本从 `data/raw/`
重建。仓库内因此不含官方表达性文本（版权顾虑消失），本地仍有完整语料（检索质量不受影响）。

**产物必须确定**：`publish_date` 取自快照 `fetch_meta.json.generated_at` 的日期部分，
**不用 `date.today()`** —— 否则隔天重跑同一快照就会产出不同的语料（与「可确定重建」矛盾）。

用法：
  python scripts/build_guides.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
GUIDES_DIR = PROJECT_ROOT / "data" / "guides"


def snapshot_publish_date(snap: Path) -> str:
    """快照的抓取日期（YYYY-MM-DD），取自 `fetch_meta.json.generated_at`。

    用快照而非当天日期，保证「同一快照 -> 同一语料」，重建结果确定可复现。
    """
    meta = load(snap / "fetch_meta.json")
    return str(meta["generated_at"])[:10]

# 关系区块 -> 该英雄页面上显示的区块名（用于语料小标题）
BLOCK_TITLE = {"hr1": "最佳搭档", "hr2": "压制英雄", "hr3": "被压制英雄"}


def latest_snapshot() -> Path:
    dirs = [Path(d) for d in glob.glob(str(RAW_DIR / "*")) if os.path.isdir(d) and not d.endswith(".cache")]
    if not dirs:
        raise SystemExit("未找到快照目录，请先运行 scripts/fetch_official.py")
    return max(dirs, key=lambda p: p.name)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def yaml_block(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def main() -> int:
    snap = latest_snapshot()
    publish_date = snapshot_publish_date(snap)
    parsed = snap / "parsed"
    heroes_all = load(parsed / "heroes_all.json")
    relations_all = load(parsed / "relations_all.json")
    items_all = load(parsed / "items_all.json")
    inscriptions_all = load(parsed / "inscriptions_all.json")

    item_name = {i["id"]: i["name"] for i in items_all}
    ming_name = {i["id"]: i["name"] for i in inscriptions_all}

    # M1b：为全量 133 英雄各生成一篇 C1 官方聚合语料
    picked = heroes_all

    GUIDES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for h in picked:
        url = h["source"]
        own = [r for r in relations_all if r["source"] == url]

        # 从本英雄页面视角还原三个区块（hr3 在全局结果中方向已反转，这里要还原成页面原样）
        page_rels = {"hr1": [], "hr2": [], "hr3": []}
        for r in own:
            if r["block"] == "hr1":
                page_rels["hr1"].append((r["to_id"], r["reason"]))
            elif r["block"] == "hr2":
                page_rels["hr2"].append((r["to_id"], r["reason"]))
            else:  # hr3：页面列的是"压制本英雄的人"，全局结果里 from 才是对方
                page_rels["hr3"].append((r["from_id"], r["reason"]))

        lines = []
        lines.append(f"# {h['name']} · 官方数据聚合")
        lines.append("")
        lines.append(f"- 英雄：{h['name']}（{h['title']}）")
        lines.append(f"- 分路：{' / '.join(h['roles'])}")
        lines.append(f"- 上手难度：{h['difficulty']}")
        lines.append("")
        lines.append("## 技能描述（官方原文）")
        for sk in h["skills"]:
            lines.append(f"- **{sk['name']}**：{sk['desc']}")
        lines.append("")
        for block in ("hr1", "hr2", "hr3"):
            rows = page_rels[block]
            if not rows:
                continue
            lines.append(f"## {BLOCK_TITLE[block]}（官方原文理由）")
            for hid, reason in rows:
                nm = next((x["name"] for x in heroes_all if x["id"] == hid), hid)
                lines.append(f"- {nm}：{reason}")
            lines.append("")
        lines.append("## 官方铭文与出装说明")
        for i, ms in enumerate(h["ming_sets"], 1):
            names = "、".join(ming_name.get(m, m) for m in ms)
            lines.append(f"- 铭文搭配{'一二'[i-1] if i<=2 else i}：{names}")
        for i, iset in enumerate(h["item_sets"], 1):
            names = " → ".join(item_name.get(it, f"未收录({it})") for it in iset)
            lines.append(f"- 推荐出装{'一二'[i-1] if i<=2 else i}：{names}")
        for tip in h["equip_tips"]:
            lines.append(f"- {tip}")
        lines.append("")

        meta = {
            "doc_id": f"c1-{h['id_name']}-official",
            "title": f"{h['name']} · 官方数据聚合（技能 / 关系 / 出装铭文）",
            "hero_ids": [h["id"]],
            "topic": "英雄资料",
            "patch": h["patch"],
            "source_url": url,
            "source_type": "official",
            "publish_date": publish_date,
            "data_source": "real",
        }
        body = yaml_block(meta) + "\n\n" + "\n".join(lines) + "\n"
        path = GUIDES_DIR / f"{meta['doc_id']}.md"
        path.write_text(body, encoding="utf-8")
        written.append(path.name)

    print(f"[guides] 快照={snap.name} 产出 C1 {len(written)} 篇：{written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
