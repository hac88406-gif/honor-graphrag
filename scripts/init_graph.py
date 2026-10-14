"""Neo4j 图谱初始化与幂等导入（规格书 4.5 / 1.10 / 6.4 阶段一）。

读 data/graph/*.json 建约束、索引，并按 MERGE 幂等写入节点与关系。
对同一份数据重复执行，节点数与关系数不增加（规格书 7 的 M1b 验收项）。

节点集（M1b 全量阶段）：
  - Hero：133 个全量英雄（含 aliases/roles/difficulty/patch/source/data_source）
  - Item：115（item.json 全量）
  - Inscription：93（ming.json 全量）
M1a 阶段曾有「5 全量英雄 + 邻居英雄桩节点」；M1b 全量入库后所有关系端点都在这 133 个之内，
桩节点数降为 0（建桩逻辑保留以兼容部分入库场景，见 DECISIONS.md）。

用法：
  python scripts/init_graph.py            # 建约束+索引并导入，打印计数
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from neo4j import GraphDatabase  # noqa: E402

from app.config import settings  # noqa: E402

GRAPH_DIR = PROJECT_ROOT / "data" / "graph"

# 规格书 4.5：唯一性约束（导入前必须建立）+ 推荐索引
CONSTRAINTS = [
    "CREATE CONSTRAINT hero_id IF NOT EXISTS FOR (h:Hero) REQUIRE h.id IS UNIQUE",
    "CREATE CONSTRAINT item_id IF NOT EXISTS FOR (i:Item) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT inscription_id IF NOT EXISTS FOR (n:Inscription) REQUIRE n.id IS UNIQUE",
]
INDEXES = [
    "CREATE INDEX hero_name IF NOT EXISTS FOR (h:Hero) ON (h.name)",
    "CREATE INDEX hero_roles IF NOT EXISTS FOR (h:Hero) ON (h.roles)",
]

HERO_REL_TYPES = ("COUNTERS", "SYNERGIZES")


def load(name: str):
    return json.loads((GRAPH_DIR / name).read_text(encoding="utf-8"))


def node_counts(session) -> dict[str, int]:
    out = {}
    for rec in session.run(
        "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY label"
    ):
        out[rec["label"]] = rec["c"]
    return out


def rel_counts(session) -> dict[str, int]:
    out = {}
    for rec in session.run(
        "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY t"
    ):
        out[rec["t"]] = rec["c"]
    return out


def import_all(session) -> dict:
    heroes = load("heroes.json")
    rels = load("relations.json")
    items = load("items.json")
    inscriptions = load("inscriptions.json")
    lookup = load("hero_lookup.json")

    for stmt in CONSTRAINTS + INDEXES:
        session.run(stmt)

    # --- 节点：全量英雄 ---
    hero_rows = [
        {
            "id": h["id"],
            "props": {
                "name": h["name"],
                "aliases": h["aliases"],
                "roles": h["roles"],
                "difficulty": h["difficulty"],
                "patch": h["patch"],
                "source": h["source"],
                "data_source": h["data_source"],
            },
        }
        for h in heroes
    ]
    session.run(
        "UNWIND $rows AS row MERGE (h:Hero {id: row.id}) SET h += row.props",
        rows=hero_rows,
    )

    # --- 节点：邻居英雄桩节点（关系端点必须存在） ---
    full_ids = {h["id"] for h in heroes}
    endpoint_ids = {r["from_id"] for r in rels} | {r["to_id"] for r in rels}
    stub_ids = sorted(endpoint_ids - full_ids)
    stub_rows = []
    for hid in stub_ids:
        info = lookup.get(hid)
        if info is None:
            raise SystemExit(f"邻居英雄 {hid} 不在 hero_lookup.json 中")
        stub_rows.append(
            {
                "id": hid,
                "props": {
                    "name": info["name"],
                    "patch": info["patch"],
                    "source": info["source"],
                    "data_source": info["data_source"],
                },
            }
        )
    session.run(
        "UNWIND $rows AS row MERGE (h:Hero {id: row.id}) "
        "SET h.name = row.props.name, h.patch = row.props.patch, "
        "h.source = row.props.source, h.data_source = row.props.data_source",
        rows=stub_rows,
    )

    # --- 节点：装备 / 铭文 ---
    session.run(
        "UNWIND $rows AS row MERGE (i:Item {id: row.id}) SET i += row.props",
        rows=[
            {
                "id": it["id"],
                "props": {
                    "name": it["name"],
                    "category": it["category"],
                    "price": it["price"],
                    "patch": it["patch"],
                    "source": it["source"],
                },
            }
            for it in items
        ],
    )
    session.run(
        "UNWIND $rows AS row MERGE (n:Inscription {id: row.id}) SET n += row.props",
        rows=[
            {
                "id": m["id"],
                "props": {
                    "name": m["name"],
                    "color": m["color"],
                    "level": m["level"],
                    "patch": m["patch"],
                    "source": m["source"],
                },
            }
            for m in inscriptions
        ],
    )

    # --- 关系：英雄-英雄（唯一键 = 起点 + 类型 + 终点 + patch，规格书 1.10） ---
    for rel_type in HERO_REL_TYPES:
        rows = [
            {
                "a": r["from_id"],
                "b": r["to_id"],
                "reason": r["reason"],
                "weight": r["weight"],
                "patch": r["patch"],
                "source": r["source"],
            }
            for r in rels
            if r["type"] == rel_type
        ]
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:Hero {{id: row.a}}), (b:Hero {{id: row.b}}) "
            f"MERGE (a)-[rel:{rel_type} {{patch: row.patch}}]->(b) "
            f"SET rel.reason = row.reason, rel.weight = row.weight, rel.source = row.source",
            rows=rows,
        )

    # --- 关系：出装（MERGE 键含 build_index/order，否则两套出装会被合并成一条） ---
    item_ids = {it["id"] for it in items}
    skipped_item_refs = 0
    item_rows = []
    for h in heroes:
        for bi, build in enumerate(h["item_sets"]):
            for order, iid in enumerate(build, start=1):
                if iid not in item_ids:
                    skipped_item_refs += 1
                    continue
                item_rows.append(
                    {
                        "hero": h["id"],
                        "item": iid,
                        "bi": bi,
                        "order": order,
                        "patch": h["patch"],
                        "source": h["source"],
                    }
                )
    session.run(
        "UNWIND $rows AS row "
        "MATCH (h:Hero {id: row.hero}), (i:Item {id: row.item}) "
        "MERGE (h)-[rel:RECOMMENDS_ITEM {build_index: row.bi, order: row.order, patch: row.patch}]->(i) "
        "SET rel.source = row.source",
        rows=item_rows,
    )

    # --- 关系：铭文搭配（MERGE 键含 build_index） ---
    ins_ids = {m["id"] for m in inscriptions}
    skipped_ins_refs = 0
    ins_rows = []
    for h in heroes:
        for bi, build in enumerate(h["ming_sets"]):
            for mid in build:
                if mid not in ins_ids:
                    skipped_ins_refs += 1
                    continue
                ins_rows.append(
                    {
                        "hero": h["id"],
                        "ins": mid,
                        "bi": bi,
                        "patch": h["patch"],
                        "source": h["source"],
                    }
                )
    session.run(
        "UNWIND $rows AS row "
        "MATCH (h:Hero {id: row.hero}), (n:Inscription {id: row.ins}) "
        "MERGE (h)-[rel:RECOMMENDS_INSCRIPTION {build_index: row.bi, patch: row.patch}]->(n) "
        "SET rel.source = row.source",
        rows=ins_rows,
    )

    return {
        "full_heroes": len(hero_rows),
        "stub_heroes": len(stub_rows),
        "items": len(items),
        "inscriptions": len(inscriptions),
        "hero_rel_rows": len(rels),
        "item_edge_rows": len(item_rows),
        "ins_edge_rows": len(ins_rows),
        "skipped_item_refs": skipped_item_refs,
        "skipped_ins_refs": skipped_ins_refs,
    }


def main() -> int:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
    )
    driver.verify_connectivity()

    with driver.session() as session:
        print("[graph] 导入前节点：", node_counts(session))
        print("[graph] 导入前关系：", rel_counts(session))
        summary = import_all(session)
        print("[graph] 本次写入：", summary)
        print("[graph] 导入后节点：", node_counts(session))
        print("[graph] 导入后关系：", rel_counts(session))

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
