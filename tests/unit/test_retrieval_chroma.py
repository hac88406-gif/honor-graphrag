"""向量检索 / BM25 / RRF 单测（规格书 4.6 / M2 验收）。

M2 验收的三项断言在本文件落地（检索层视角，与 M1b 的 collection 级用例互补）：
  1. **元数据算子差异**：同一查询用 `$in`（预期空）与 `$contains`（预期有命中）各跑一次；
  2. **embedding function 重启回归**：重开 PersistentClient + 显式传 EF，同一句结果一致；
  3. **版本过滤实际召回**：写入一条旧 patch 文档，断言它不被召回（断言 ids，不是 count）。

离线用例（build_where / rrf_fuse / tokenize）不依赖任何外部服务；其余用例走 `require_chroma`
门禁（见 tests/conftest.py）：开发模式跳过（视为「未执行」），**验收模式（REQUIRE_SERVICES=1）下 fail**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.retrieval import bm25, chroma_client
from app.utils.chroma import COLLECTION_NAME, get_client, get_collection

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DIAOCHAN = "141"           # 貂蝉 ename（语料 hero_ids 中的值）
QUERY = "貂蝉怎么出装"
TMP_COLLECTION = "m2_version_filter_ut"


@pytest.fixture(scope="module")
def guides_collection():
    """已建好的 guides collection（走统一 get_collection，显式传 bge EF）。

    本夹具**不**自行 skip —— 门禁由 `require_chroma` 在**用例体内**执行：
    `pytest.fail` 需发生在用例体中才会被计为 failed（11.3 v1.5 的 fail-fast 要求）。
    未建库时返回 None，用例会先调 `require_chroma()` 停下。
    """
    if COLLECTION_NAME not in [c.name for c in get_client().list_collections()]:
        return None
    return get_collection()


# ---------------------------------------------------------------- 离线

def test_build_where_operator_mapping():
    """build_where 必须按字段类型选算子：patch（标量）用 $in，hero_ids（列表）用 $contains。"""
    both = chroma_client.build_where(hero_id=DIAOCHAN, patches=["2026-10"])
    assert both == {"$and": [
        {"patch": {"$in": ["2026-10"]}},
        {"hero_ids": {"$contains": DIAOCHAN}},
    ]}
    # 单条件不包 $and
    assert chroma_client.build_where(hero_id=DIAOCHAN) == {"hero_ids": {"$contains": DIAOCHAN}}
    assert chroma_client.build_where(patches=["2026-10"]) == {"patch": {"$in": ["2026-10"]}}
    assert chroma_client.build_where() is None
    # 明确排除错误算子
    assert "$in" not in str(chroma_client.build_where(hero_id=DIAOCHAN))


def test_corpus_metadata_omits_empty_list_values():
    """空列表 metadata 值必须省略键。

    chromadb 1.5.9 对空列表直接抛
    `ValueError: Expected metadata list value for key 'hero_ids' to be non-empty`，
    而「不带英雄的通用语料」（版本理解 / 意识类）是合法形态（TIER_META 路径按 patch 过滤即可召回）。
    故空列表省略键 —— 省略后 `{"hero_ids": {"$contains": id}}` 天然不匹配，语义正确。
    上传端点与全库重建都经 `corpus_metadata` 转换，本用例把这条约束钉住。
    """
    from app.utils.chroma import corpus_metadata

    keys = ["doc_id", "hero_ids", "patch"]
    assert corpus_metadata({"doc_id": "d1", "hero_ids": [], "patch": "2026-10"}, keys) == {
        "doc_id": "d1",
        "patch": "2026-10",
    }, "空列表必须被省略，写空值会让 chromadb 拒绝整批入库"
    assert corpus_metadata({"doc_id": "d1", "hero_ids": ["141"], "patch": "2026-10"}, keys)[
        "hero_ids"
    ] == ["141"], "非空列表必须原样保留（它是 hero 过滤的依据）"


def test_rrf_fuse_ranks_shared_doc_first():
    """RRF：两路都命中的文档融合分最高（只吃排名不吃分数）。"""
    fused = bm25.rrf_fuse([["a", "b", "c"], ["b", "d"]])
    order = [d for d, _ in fused]
    assert order[0] == "b", "两路同时命中的 b 应排第一"
    assert set(order) == {"a", "b", "c", "d"}
    # 校验分值公式：sum 1/(k + rank)
    score = dict(fused)
    assert score["b"] == pytest.approx(1 / (settings.RRF_K + 2) + 1 / (settings.RRF_K + 1))


def test_tokenize_drops_punctuation():
    """jieba 分词后丢弃标点，词表只含实词。"""
    toks = bm25.tokenize("貂蝉怎么出装？")
    assert "貂蝉" in toks
    assert "？" not in toks


# ---------------------------------------------------------------- 算子差异（M2 断言 1）

def test_metadata_operator_in_vs_contains(guides_collection, require_chroma):
    """hero_ids 是列表字段：$in 静默返回空，$contains 才命中（把差异固化）。"""
    require_chroma()
    res_in = guides_collection.query(
        query_texts=[QUERY], n_results=5, where={"hero_ids": {"$in": [DIAOCHAN]}}
    )
    res_contains = guides_collection.query(
        query_texts=[QUERY], n_results=5, where={"hero_ids": {"$contains": DIAOCHAN}}
    )
    assert res_in["ids"][0] == [], "$in 对列表字段应静默返回空（这正是要固化的差异）"
    assert len(res_contains["ids"][0]) > 0, "$contains 应命中（否则列表字段过滤失效）"


def test_hero_filter_actual_recall(guides_collection, require_chroma):
    """实际召回：带 hero_id 过滤时，返回的每条都属该英雄（防跨英雄串味）。"""
    require_chroma()
    ev = chroma_client.search(QUERY, hero_id=DIAOCHAN, top_k=5)
    assert ev, "带英雄过滤应有召回"
    assert all(DIAOCHAN in e.hero_ids for e in ev), "召回结果混入了其他英雄的语料"


# ---------------------------------------------------------------- EF 重启回归（M2 断言 2）

def test_ef_restart_regression(require_chroma):
    """写入 → 重开 client → 重取 collection（显式传 EF）→ 查同一句，命中 id/距离一致。

    若重开时漏传 EF，chromadb 回退默认 ONNX 模型，查询向量与写入向量不同源，
    ids/distances 将与重启前不一致——本用例把该静默失败钉死。
    """
    import chromadb

    from app.utils.chroma import load_embedding_function

    require_chroma()

    where = chroma_client.build_where(hero_id=DIAOCHAN, patches=settings.PATCH_WINDOW)
    before = chroma_client.raw_query(QUERY, hero_id=DIAOCHAN, top_k=3)

    client_after = chromadb.PersistentClient(path=str(PROJECT_ROOT / settings.CHROMA_PERSIST_DIR))
    collection_after = client_after.get_collection(
        name=COLLECTION_NAME, embedding_function=load_embedding_function()
    )
    after = collection_after.query(
        query_texts=[QUERY], n_results=3, where=where,
        include=["documents", "metadatas", "distances"],
    )

    assert before["ids"][0] == after["ids"][0], "重启后重取 collection 的命中 id 不一致（EF 未同源？）"
    assert before["distances"][0] == pytest.approx(after["distances"][0], rel=1e-6), (
        "重启前后距离不一致，说明查询向量与写入向量不同源"
    )


# ---------------------------------------------------------------- 版本过滤（M2 断言 3）

def test_version_filter_actual_recall():
    """写入一条旧 patch 文档：断言它**不被召回**（断言 ids，不能只测 count）。

    用临时 collection 构造「同语义、不同 patch」的两条文档，避免依赖正式库恰好有旧 patch 数据。
    """
    from app.utils.chroma import load_embedding_function

    client = get_client()
    try:
        client.delete_collection(TMP_COLLECTION)
    except Exception:  # noqa: BLE001 - 不存在即忽略
        pass
    client.create_collection(TMP_COLLECTION, embedding_function=load_embedding_function())

    try:
        col = get_collection(TMP_COLLECTION)
        col.add(
            ids=["old#0", "new#0"],
            documents=[
                "这是一条旧版本补丁的攻略文本，讲貂蝉出装思路。",
                "这是一条当前版本的攻略文本，讲貂蝉出装思路。",
            ],
            metadatas=[
                {"patch": "2026-01", "hero_ids": [DIAOCHAN]},
                {"patch": "2026-10", "hero_ids": [DIAOCHAN]},
            ],
        )

        where = {"patch": {"$in": list(settings.PATCH_WINDOW)}}
        res = col.query(query_texts=[QUERY], n_results=10, where=where)
        ids = res["ids"][0]
        assert "new#0" in ids, "窗口内文档应被召回"
        assert "old#0" not in ids, "窗口外（旧 patch）文档不得被召回"

        # 不过滤时两条都在 —— 证明差异来自版本过滤，而非数据缺失
        res_all = col.query(query_texts=[QUERY], n_results=10)
        assert set(res_all["ids"][0]) == {"old#0", "new#0"}
    finally:
        client.delete_collection(TMP_COLLECTION)


# ---------------------------------------------------------------- 混合检索

def test_hybrid_search_returns_evidence(guides_collection, require_chroma):
    """向量 + BM25 经 RRF 融合后返回 5.1 结构的 Evidence（kind=vector、带 source_url）。"""
    require_chroma()
    ev = bm25.hybrid_search(QUERY, hero_id=DIAOCHAN, top_k=3)
    assert ev, "混合检索应有召回"
    e = ev[0]
    assert e.kind == "vector"
    assert e.content
    assert e.source_url
    assert DIAOCHAN in e.hero_ids
