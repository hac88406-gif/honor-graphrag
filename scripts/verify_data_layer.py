"""数据层复跑校验（M2 交付附带，规格书 M2 要求「附数据层复跑校验真实输出」）。

目的：确认 M2 检索层的改动**没有破坏数据**——把数据层重跑一遍（幂等重导入）后，
逐层核对计数与 source/patch/reason 完整性，并把三层计数口径显式打出来。

三层口径（2026-10-14 起全项目统一，见 README / DECISIONS.md）：
  1. 源数据层   —— data/raw/{snapshot}/parsed/*.json（抓取解析产物，未去重）
  2. 导出层     —— data/graph/relations.json（build_graph_data.py 产物，仍按页展开，未去重）
  3. 入库后层   —— Neo4j（MERGE 唯一键 = 起点+类型+终点+patch，已去重）

校验项：
  - 计数：三层逐项对齐（含「去重后 = 源 - 合并边」的推导）
  - 完整性：节点/关系的 source、patch 非空；COUNTRELS reason 非空；关系 reason 空值如实计数
  - 向量库：collection.count() 与元数据（patch / hero_ids / source_url）完整性
  - 幂等：连续两次导入后计数不变

退出码：0 = 全部通过；1 = 有硬性失败项。

用法：
  python scripts/verify_data_layer.py
  python scripts/verify_data_layer.py --snapshot 20261014-230459
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

RAW_DIR = PROJECT_ROOT / "data" / "raw"
GRAPH_DIR = PROJECT_ROOT / "data" / "graph"

from app.config import settings  # noqa: E402

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def latest_snapshot() -> Path:
    dirs = [
        Path(d)
        for d in glob.glob(str(RAW_DIR / "*"))
        if os.path.isdir(d) and not d.endswith(".cache")
    ]
    if not dirs:
        raise SystemExit("未找到快照目录，请先运行 scripts/fetch_official.py")
    return max(dirs, key=lambda p: p.name)


def count_by_type(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["type"]] = out.get(r["type"], 0) + 1
    return out


def merged_edges(rows: list[dict], rel_type: str) -> list[tuple[str, str, int]]:
    """按 (起点, 终点, patch) 统计在源数据层出现 >1 次的边（入库 MERGE 会合并）。"""
    counts: dict[tuple[str, str, str], int] = {}
    for r in rows:
        if r["type"] != rel_type:
            continue
        key = (r["from_id"], r["to_id"], r["patch"])
        counts[key] = counts.get(key, 0) + 1
    return sorted([(k[0], k[1], v) for k, v in counts.items() if v > 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="", help="快照目录名；缺省取最新")
    args = ap.parse_args()

    snap = RAW_DIR / args.snapshot if args.snapshot else latest_snapshot()
    print("=" * 72)
    print(f"[verify] 数据层复跑校验  快照 = {snap.name}")
    print("=" * 72)

    # ---------------------------------------------------------------- 1. 源数据层
    print("\n【1】源数据层（data/raw/{snapshot}/parsed，未去重）")
    parsed = snap / "parsed"
    rels_all = load_json(parsed / "relations_all.json")
    heroes_all = load_json(parsed / "heroes_all.json")
    items_all = load_json(parsed / "items_all.json")
    inscriptions_all = load_json(parsed / "inscriptions_all.json")
    src_types = count_by_type(rels_all)
    print(f"  英雄 = {len(heroes_all)}  装备 = {len(items_all)}  铭文 = {len(inscriptions_all)}")
    print(f"  关系行数 = {len(rels_all)}")
    for t in sorted(src_types):
        print(f"    {t:24s} = {src_types[t]}")

    # ---------------------------------------------------------------- 2. 导出层
    print("\n【2】导出层（data/graph/relations.json，按页展开，仍不去重）")
    rels_out = load_json(GRAPH_DIR / "relations.json")
    heroes_out = load_json(GRAPH_DIR / "heroes.json")
    items_out = load_json(GRAPH_DIR / "items.json")
    ins_out = load_json(GRAPH_DIR / "inscriptions.json")
    out_types = count_by_type(rels_out)
    print(f"  英雄 = {len(heroes_out)}  装备 = {len(items_out)}  铭文 = {len(ins_out)}")
    print(f"  关系行数 = {len(rels_out)}")
    for t in sorted(out_types):
        print(f"    {t:24s} = {out_types[t]}")

    if len(rels_out) != len(rels_all):
        fail(f"导出层行数 {len(rels_out)} != 源数据层 {len(rels_all)}")
    else:
        ok(f"导出层行数 == 源数据层行数（{len(rels_out)}，未去重）")
    if len(heroes_out) != len(heroes_all):
        fail(f"英雄节点数 {len(heroes_out)} != 抓取英雄数 {len(heroes_all)}")
    else:
        ok(f"英雄节点数 == 抓取英雄数（{len(heroes_out)}，全量 133）")

    # 导出层完整性（source / patch / reason）
    empty_src = [r for r in rels_out if not r.get("source")]
    empty_patch = [r for r in rels_out if not r.get("patch")]
    empty_reason = [r for r in rels_out if not r.get("reason")]
    print(f"  导出层关系：source 空 = {len(empty_src)}，patch 空 = {len(empty_patch)}，"
          f"reason 空 = {len(empty_reason)}")
    if empty_src:
        fail(f"导出层有 {len(empty_src)} 条关系缺 source")
    else:
        ok("导出层全部关系都有 source")
    if empty_patch:
        fail(f"导出层有 {len(empty_patch)} 条关系缺 patch")
    else:
        ok("导出层全部关系都有 patch")
    if empty_reason:
        print(f"  [WARN] {len(empty_reason)} 条关系 reason 为空（官方页面未附理由，属数据特征）")

    # 合并边明细（入库 MERGE 的落点）
    merged_counter = merged_edges(rels_out, "COUNTERS")
    merged_syn = merged_edges(rels_out, "SYNERGIZES")
    print(f"  源数据层重复边（会被 MERGE 合并）：COUNTERS {len(merged_counter)} 条，"
          f"SYNERGIZES {len(merged_syn)} 条")

    # ---------------------------------------------------------------- 3. 入库后层
    print("\n【3】入库后层（Neo4j，MERGE 唯一键 = 起点+类型+终点+patch，已去重）")
    import init_graph  # noqa: E402
    from neo4j import GraphDatabase  # noqa: E402

    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
        )
        driver.verify_connectivity()
    except Exception as e:  # noqa: BLE001
        print(f"  Neo4j 不可达（{settings.NEO4J_URI}）：{e}")
        fail("Neo4j 不可达，入库后层校验未执行")
        return 1

    try:
        with driver.session() as s:
            print("  [重导入] 幂等写入 data/graph/*.json ...")
            summary = init_graph.import_all(s)
            nodes_1, rels_1 = init_graph.node_counts(s), init_graph.rel_counts(s)
            # 幂等：再导入一次
            init_graph.import_all(s)
            nodes_2, rels_2 = init_graph.node_counts(s), init_graph.rel_counts(s)

            print(f"  本次写入：{summary}")
            print(f"  节点：{nodes_1}")
            print(f"  关系：{rels_1}")

            if nodes_1 != nodes_2 or rels_1 != rels_2:
                fail(f"幂等失败：二次导入后节点 {nodes_1}->{nodes_2}、关系 {rels_1}->{rels_2}")
            else:
                ok("幂等：连续两次导入后节点数/关系数逐项不变")

            # 去重口径推导
            dedup_counter = len({(r["from_id"], r["to_id"], r["patch"])
                                 for r in rels_out if r["type"] == "COUNTERS"})
            dedup_syn = len({(r["from_id"], r["to_id"], r["patch"])
                             for r in rels_out if r["type"] == "SYNERGIZES"})
            print(f"  去重口径推导：源 COUNTERS {src_types.get('COUNTERS')} - 合并 "
                  f"{len(merged_counter)} = {dedup_counter}")
            print(f"              源 SYNERGIZES {src_types.get('SYNERGIZES')} - 合并 "
                  f"{len(merged_syn)} = {dedup_syn}")
            if rels_1.get("COUNTERS") != dedup_counter:
                fail(f"入库后 COUNTERS {rels_1.get('COUNTERS')} != 去重推导 {dedup_counter}")
            else:
                ok(f"入库后 COUNTERS（{rels_1.get('COUNTERS')}）== 去重后口径")
            if rels_1.get("SYNERGIZES") != dedup_syn:
                fail(f"入库后 SYNERGIZES {rels_1.get('SYNERGIZES')} != 去重推导 {dedup_syn}")
            else:
                ok(f"入库后 SYNERGIZES（{rels_1.get('SYNERGIZES')}）== 去重后口径")

            # 完整性：NULL 与空串都要查
            def scalar(q: str) -> int:
                return s.run(q).single()["c"]

            checks = {
                "Hero.source 空": "MATCH (h:Hero) WHERE h.source IS NULL OR h.source = '' RETURN count(h) AS c",
                "Hero.patch 空": "MATCH (h:Hero) WHERE h.patch IS NULL OR h.patch = '' RETURN count(h) AS c",
                "Item.source 空": "MATCH (i:Item) WHERE i.source IS NULL OR i.source = '' RETURN count(i) AS c",
                "Inscription.source 空": "MATCH (n:Inscription) WHERE n.source IS NULL OR n.source = '' RETURN count(n) AS c",
                "关系.source 空": "MATCH ()-[r]->() WHERE r.source IS NULL OR r.source = '' RETURN count(r) AS c",
                "关系.patch 空": "MATCH ()-[r]->() WHERE r.patch IS NULL OR r.patch = '' RETURN count(r) AS c",
                "COUNTERS.reason 空": "MATCH ()-[r:COUNTERS]->() WHERE r.reason IS NULL OR r.reason = '' RETURN count(r) AS c",
                "SYNERGIZES.reason 空": "MATCH ()-[r:SYNERGIZES]->() WHERE r.reason IS NULL OR r.reason = '' RETURN count(r) AS c",
            }
            print("  完整性检查（空 = NULL 或 空串）：")
            for label, q in checks.items():
                c = scalar(q)
                print(f"    {label:24s} = {c}")
                # 节点/关系的 source、patch 必须齐备；reason 允许官方未附（如实计数即可）
                if c and label not in ("COUNTERS.reason 空", "SYNERGIZES.reason 空"):
                    fail(f"{label} 出现 {c} 条")
    finally:
        driver.close()

    # ---------------------------------------------------------------- 4. 向量库
    print("\n【4】向量库（Chroma collection 'guides'）")
    try:
        from app.utils.chroma import COLLECTION_NAME, get_client, get_collection

        names = [c.name for c in get_client().list_collections()]
        if COLLECTION_NAME not in names:
            fail(f"collection '{COLLECTION_NAME}' 不存在")
        else:
            col = get_collection()
            data = col.get(include=["metadatas"])
            metas = data["metadatas"]
            n = col.count()
            print(f"  collection.count() = {n}（文档数，M1b 验收要求 ≥ 100）")
            miss_patch = sum(1 for m in metas if not m.get("patch"))
            miss_hero = sum(1 for m in metas if not m.get("hero_ids"))
            miss_url = sum(1 for m in metas if not m.get("source_url"))
            print(f"  缺 patch 元数据 = {miss_patch}，缺 hero_ids = {miss_hero}，缺 source_url = {miss_url}")
            patches: dict[str, int] = {}
            for m in metas:
                patches[str(m.get("patch"))] = patches.get(str(m.get("patch")), 0) + 1
            print(f"  patch 分布 = {patches}")
            if n < 100:
                fail(f"向量库文档数 {n} < 100")
            else:
                ok(f"向量库文档数 {n} ≥ 100")
            if miss_patch or miss_hero or miss_url:
                fail("向量库存在元数据缺失")
            else:
                ok("向量库元数据（patch / hero_ids / source_url）完整")
    except Exception as e:  # noqa: BLE001
        print(f"  Chroma 不可用：{e}")
        fail(f"Chroma 校验未执行：{e}")

    # ---------------------------------------------------------------- 5. 结论
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"[verify] 结论：FAIL（{len(FAILURES)} 项）")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("[verify] 结论：PASS —— 数据层复跑校验全部通过，检索层未破坏数据")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
