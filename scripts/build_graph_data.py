"""从最新抓取快照导出阶段一入库数据（规格书 6.4 阶段一 / M1b 全量阶段）。

输入：data/raw/{timestamp}/parsed/*.json（fetch_official.py 的产物）+ data/hero_aliases.json
输出：data/graph/heroes.json, relations.json, items.json, inscriptions.json

与 fetch 分离的原因：抓取是网络操作，导出是纯变换。别名是人工维护的语料，
会随审核反复调整，不该为了改别名而重跑抓取（即便命中缓存）。

M1a 只导出 5 个样例英雄；**M1b 起导出全量 133 英雄**（规格书 3.4 目标「英雄节点 133」），
桩节点机制随全量入库自然消失（所有关系端点都在这 133 个之内）。

用法：
  python scripts/build_graph_data.py
  python scripts/build_graph_data.py --snapshot 20261014-230459
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
GRAPH_DIR = PROJECT_ROOT / "data" / "graph"
ALIASES_FILE = PROJECT_ROOT / "data" / "hero_aliases.json"

# M1a 的 5 个样例英雄（别名已维护，规格书 6.4）。其余英雄节点 aliases 暂为空列表，
# 待 M2 实体链接层按需补齐（见 DECISIONS.md 2026-10-14 M1b 条）。
SAMPLE_HEROES = ["亚瑟", "兰陵王", "貂蝉", "后羿", "东皇太一"]


def latest_snapshot() -> Path:
    dirs = [
        Path(d)
        for d in glob.glob(str(RAW_DIR / "*"))
        if os.path.isdir(d) and not d.endswith(".cache")
    ]
    if not dirs:
        raise SystemExit("未找到快照目录，请先运行 scripts/fetch_official.py")
    return max(dirs, key=lambda p: p.name)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="", help="快照目录名；缺省取最新")
    args = ap.parse_args()

    snap = RAW_DIR / args.snapshot if args.snapshot else latest_snapshot()
    parsed = snap / "parsed"
    if not parsed.exists():
        raise SystemExit(f"快照 {snap.name} 缺少 parsed/ 目录")
    print(f"[build] 快照 = {snap.name}")

    heroes_all = load_json(parsed / "heroes_all.json")
    relations_all = load_json(parsed / "relations_all.json")
    items_all = load_json(parsed / "items_all.json")
    inscriptions_all = load_json(parsed / "inscriptions_all.json")

    alias_map = {a["name"]: a["aliases"] for a in load_json(ALIASES_FILE)}

    name_by_id = {h["id"]: h["name"] for h in heroes_all}

    # M1b：全量入库 133 英雄（规格书 3.4「英雄节点 133」）
    picked = heroes_all
    ids = {h["id"] for h in picked}

    # 别名语料（data/hero_aliases.json）只覆盖 M1a 的 5 个样例英雄；
    # 其余英雄 aliases 取空列表，待 M2 实体链接层按需补齐。
    alias_outside = set(alias_map) - {h["name"] for h in heroes_all}
    if alias_outside:
        raise SystemExit(f"hero_aliases.json 中的英雄不在抓取结果中：{sorted(alias_outside)}")

    hero_nodes = []
    for h in picked:
        hero_nodes.append(
            {
                "id": h["id"],
                "name": h["name"],
                "aliases": alias_map.get(h["name"], []),
                "roles": h["roles"],
                "difficulty": h["difficulty"],
                "patch": h["patch"],
                "source": h["source"],
                "data_source": h["data_source"],
                # 以下为出装/铭文搭配边的来源（规格书 4.5：RECOMMENDS_* 由英雄侧数据派生）
                "item_sets": h["item_sets"],
                "ming_sets": h["ming_sets"],
                "skills": h["skills"],
                "equip_tips": h["equip_tips"],
            }
        )

    # 关系：M1b 全量入库，纳入全部英雄-英雄关系（端点必在这 133 个之内）。
    # 带上端点中文名，供 init_graph.py 兜底建桩节点（全量后桩数应为 0）。
    rels = []
    for r in relations_all:
        if r["from_id"] in ids or r["to_id"] in ids:
            rels.append(
                {
                    "from_id": r["from_id"],
                    "from_name": name_by_id.get(r["from_id"], ""),
                    "to_id": r["to_id"],
                    "to_name": name_by_id.get(r["to_id"], ""),
                    "type": r["type"],
                    "block": r["block"],
                    "reason": r["reason"],
                    "weight": r["weight"],
                    "patch": r["patch"],
                    "source": r["source"],
                }
            )

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    (GRAPH_DIR / "heroes.json").write_text(json.dumps(hero_nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    (GRAPH_DIR / "relations.json").write_text(json.dumps(rels, ensure_ascii=False, indent=2), encoding="utf-8")
    (GRAPH_DIR / "items.json").write_text(json.dumps(items_all, ensure_ascii=False, indent=2), encoding="utf-8")
    (GRAPH_DIR / "inscriptions.json").write_text(json.dumps(inscriptions_all, ensure_ascii=False, indent=2), encoding="utf-8")

    # 解析表：全部 133 英雄的 id -> 节点属性。init_graph.py 用它为关系里的"外部端点"
    # 建桩节点（规格书 4.5 要求节点带 source；桩节点也必须有真实官方 URL）。
    lookup = {
        h["id"]: {
            "name": h["name"],
            "id_name": h["id_name"],
            "roles": h["roles"],
            "patch": h["patch"],
            "source": h["source"],
            "data_source": h["data_source"],
        }
        for h in heroes_all
    }
    (GRAPH_DIR / "hero_lookup.json").write_text(json.dumps(lookup, ensure_ascii=False, indent=2), encoding="utf-8")

    neighbor_ids = {r["from_id"] for r in rels} | {r["to_id"] for r in rels}
    print(f"[build] heroes={len(hero_nodes)} relations={len(rels)} items={len(items_all)} "
          f"inscriptions={len(inscriptions_all)} 邻居英雄={len(neighbor_ids - ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
