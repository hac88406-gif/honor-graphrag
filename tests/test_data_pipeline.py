"""M1b 数据层回归测试。

把 M1b 之前「跑两遍给人看」的校验固化为可重复执行的 pytest 用例（规格书 M1b 要求）：

  1. test_neo4j_import_idempotent        —— 同一份数据导入两次，节点数/关系数不变
  2. test_relation_pairing_lengths       —— 每页三区块「英雄列表长度 == 理由列表长度」
  3. test_list_field_operator_in_vs_contains —— hero_ids 列表字段：$in 静默返回空、$contains 有命中
  4. test_ef_restart_regression          —— 写入 → 重启 → 重取 collection → 同一句查询结果一致

依赖说明：用例 1 需 Neo4j 可达、用例 3/4 需已建好的 Chroma collection（scripts/init_chroma.py）。
依赖缺失时走 `require_neo4j` / `require_chroma` 门禁（见 tests/conftest.py）：
开发模式跳过（视为「未执行」），**验收模式（REQUIRE_SERVICES=1）下 fail**。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

QUERY_TEXT = "貂蝉怎么出装"
HERO_ID_DIAOCHAN = "141"  # 貂蝉 ename，语料 hero_ids 中的值


# ---------------------------------------------------------------- 工具

def latest_snapshot() -> Path:
    dirs = [p for p in RAW_DIR.iterdir() if p.is_dir() and p.name != ".cache"]
    assert dirs, f"{RAW_DIR} 下没有抓取快照，请先运行 scripts/fetch_official.py"
    return max(dirs, key=lambda p: p.name)


@pytest.fixture(scope="module")
def guides_collection():
    """已建好的 guides collection（显式传 bge EF 获取）。

    本夹具不自行 skip；门禁由 `require_chroma` 在用例体内执行（11.3 v1.5：验收模式必须 fail）。
    """
    from app.utils.chroma import COLLECTION_NAME, get_client, get_collection

    if COLLECTION_NAME not in [c.name for c in get_client().list_collections()]:
        return None
    return get_collection()


# ---------------------------------------------------------------- 1. 幂等

def test_neo4j_import_idempotent(require_neo4j):
    """同一份 data/graph/*.json 连续导入两次，节点数与关系数必须逐项不变。"""
    import init_graph
    from neo4j import GraphDatabase

    from app.config import settings

    require_neo4j()

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
    )

    try:
        with driver.session() as s:
            init_graph.import_all(s)
            nodes_1, rels_1 = init_graph.node_counts(s), init_graph.rel_counts(s)
            init_graph.import_all(s)
            nodes_2, rels_2 = init_graph.node_counts(s), init_graph.rel_counts(s)
    finally:
        driver.close()

    assert nodes_1 == nodes_2, f"第二次导入后节点数变化：{nodes_1} -> {nodes_2}"
    assert rels_1 == rels_2, f"第二次导入后关系数变化：{rels_1} -> {rels_2}"


# ---------------------------------------------------------------- 2. 配对

def test_relation_pairing_lengths():
    """每页三区块的「英雄列表长度 == 理由列表长度」必须成立。

    scripts/fetch_official.py 的 parse_relations() 在不匹配时抛 RelationPairError，
    因此「全量页面重新解析无异常」本身就是该断言的固化；再逐区块断言恰为 2 条
    （官方数据口径：每页每区块恰 2 条），防止静默少解析。
    """
    import fetch_official as fo

    snap = latest_snapshot()
    detail_dir = snap / "herodetail"
    htmls = sorted(detail_dir.glob("*.shtml"))
    assert htmls, f"{detail_dir} 下无详情页快照"

    for path in htmls:
        html = path.read_text(encoding="utf-8")
        # 长度不一致时此处抛 RelationPairError（即测试失败）
        parsed = fo.parse_relations(html, path.stem)
        for key in fo.REL_BLOCKS:
            assert len(parsed[key]) == 2, (
                f"{path.stem} 区块 {fo.REL_BLOCKS[key][0]} 条数 {len(parsed[key])} != 2"
            )

    errors = json.loads((snap / "parsed" / "parse_errors.json").read_text(encoding="utf-8"))
    assert errors == [], f"快照存在解析失败项：{errors}"


# ---------------------------------------------------------------- 3. 算子差异

def test_list_field_operator_in_vs_contains(guides_collection):
    """hero_ids 是列表字段：chromadb 1.5.9 下 $in 静默返回空，$contains 才命中。"""
    where_in = {"hero_ids": {"$in": [HERO_ID_DIAOCHAN]}}
    where_contains = {"hero_ids": {"$contains": HERO_ID_DIAOCHAN}}

    res_in = guides_collection.query(query_texts=[QUERY_TEXT], n_results=5, where=where_in)
    res_contains = guides_collection.query(query_texts=[QUERY_TEXT], n_results=5, where=where_contains)

    assert len(res_in["ids"][0]) == 0, "$in 对列表字段应静默返回空（这正是要固化的差异）"
    assert len(res_contains["ids"][0]) > 0, "$contains 应命中（否则列表字段过滤失效）"


# ---------------------------------------------------------------- 4. EF 重启回归

def test_ef_restart_regression(guides_collection, require_chroma):
    """写入 → 重启 → 重取 collection → 查同一句，结果必须一致。

    「重启」用「全新 PersistentClient + 显式传 bge EF 重新 get_collection」模拟：
    若重开时漏传 EF，chromadb 会回退默认 ONNX 模型，查询向量与写入向量不同源，
    返回的 ids/distances 将与重启前不一致——本用例即把该静默失败钉死。
    """
    import chromadb

    from app.config import settings
    from app.utils.chroma import COLLECTION_NAME, load_embedding_function

    require_chroma()

    where = {"hero_ids": {"$contains": HERO_ID_DIAOCHAN}}
    before = guides_collection.query(query_texts=[QUERY_TEXT], n_results=3, where=where)

    client_after_restart = chromadb.PersistentClient(
        path=str(PROJECT_ROOT / settings.CHROMA_PERSIST_DIR)
    )
    collection_after_restart = client_after_restart.get_collection(
        name=COLLECTION_NAME, embedding_function=load_embedding_function()
    )
    after = collection_after_restart.query(query_texts=[QUERY_TEXT], n_results=3, where=where)

    assert before["ids"][0] == after["ids"][0], "重启后重取 collection 的命中 id 不一致（EF 未同源？）"
    assert before["distances"][0] == pytest.approx(after["distances"][0], rel=1e-6), (
        "重启前后距离不一致，说明查询向量与写入向量不同源"
    )
