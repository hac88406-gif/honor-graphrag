"""BM25 混合检索 + RRF 融合（规格书 4.6「可选加分项」，10 号裁定：v1 加上）。

理由（4.6）：英雄名、装备名这类**专有名词**对纯语义模型不敏感（bge 会把「铠」和「凯」
当成近义），但 BM25 能精确命中字面。实现成本低、效果提升明显。

中文分词必须用 jieba（4.12 依赖清单标 ★）：rank_bm25 没有中文分词能力，
缺它只能按字切，BM25 的词频统计会失真。

融合用 RRF（Reciprocal Rank Fusion）：`score(d) = Σ_r 1/(k + rank_r(d))`。
RRF 只吃**排名**不吃分数，因此不需要把余弦相似度和 BM25 分值归一化到同一量纲——
这正是它在异构检索器融合上稳健的原因。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import jieba

from app.config import settings
from app.schemas.chat import Evidence
from app.utils.chroma import COLLECTION_NAME, get_collection

logger = logging.getLogger(__name__)

_PUNCT = set("，。！？；：、（）【】《》〈〉“”‘’·—…～!?,.:;()[]{}<>\"'`~@#$%^&*+=|\\/-_ \t\n\r")


def tokenize(text: str) -> list[str]:
    """jieba 分词并丢掉标点/空白（BM25 的词表只应含实词）。"""
    return [t for t in jieba.lcut(text) if t and t not in _PUNCT and t.strip()]


@dataclass
class _Corpus:
    ids: list[str]
    docs: list[str]
    metas: list[dict]
    bm25: object  # rank_bm25.BM25Okapi


_cache: dict[str, _Corpus] = {}


def _load_corpus(collection_name: str = COLLECTION_NAME) -> _Corpus:
    if collection_name in _cache:
        return _cache[collection_name]

    from rank_bm25 import BM25Okapi

    collection = get_collection(collection_name)
    data = collection.get(include=["documents", "metadatas"])
    ids = list(data["ids"])
    docs = list(data["documents"])
    metas = [dict(m) for m in data["metadatas"]]
    corpus = _Corpus(ids=ids, docs=docs, metas=metas, bm25=BM25Okapi([tokenize(d) for d in docs]))
    _cache[collection_name] = corpus
    return corpus


def invalidate(collection_name: str | None = None) -> None:
    """丢弃 BM25 索引缓存（collection 重建或测试用临时库后调用）。"""
    if collection_name is None:
        _cache.clear()
    else:
        _cache.pop(collection_name, None)


def _meta_match(meta: dict, hero_id: str | None, patches: list[str] | None) -> bool:
    if patches and meta.get("patch") not in patches:
        return False
    if hero_id and hero_id not in list(meta.get("hero_ids", [])):
        return False
    return True


def search(
    query: str,
    *,
    hero_id: str | None = None,
    patches: list[str] | None = None,
    top_k: int | None = None,
    collection_name: str = COLLECTION_NAME,
) -> list[tuple[str, str, dict, float]]:
    """BM25 检索。返回 [(id, doc, meta, score), ...]，按分值降序，已按 hero/patch 过滤。"""
    corpus = _load_corpus(collection_name)
    if not corpus.ids:
        return []
    scores = corpus.bm25.get_scores(tokenize(query))
    window = list(settings.PATCH_WINDOW) if patches is None else list(patches)
    ranked = sorted(range(len(corpus.ids)), key=lambda i: scores[i], reverse=True)

    out: list[tuple[str, str, dict, float]] = []
    n = top_k or settings.BM25_TOP_K
    for i in ranked:
        if scores[i] <= 0:
            break
        meta = corpus.metas[i]
        if not _meta_match(meta, hero_id, window):
            continue
        out.append((corpus.ids[i], corpus.docs[i], meta, float(scores[i])))
        if len(out) >= n:
            break
    return out


def rrf_fuse(rankings: list[list[str]], k: int | None = None) -> list[tuple[str, float]]:
    """RRF 融合多路排名。rankings 是若干「已按相关性降序排列的 id 列表」。"""
    kk = settings.RRF_K if k is None else k
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (kk + rank)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


def hybrid_search(
    query: str,
    *,
    hero_id: str | None = None,
    patches: list[str] | None = None,
    top_k: int | None = None,
    collection_name: str = COLLECTION_NAME,
) -> list[Evidence]:
    """向量 + BM25 双路召回 -> RRF 融合 -> Evidence 列表（按融合序）。"""
    from app.retrieval import chroma_client

    n = top_k or settings.VECTOR_TOP_K
    vec = chroma_client.raw_query(
        query, hero_id=hero_id, patches=patches, top_k=n, collection_name=collection_name
    )
    vec_ids = list(vec["ids"][0])
    vec_by_id = {
        cid: (doc, meta, dist)
        for cid, doc, meta, dist in zip(
            vec["ids"][0], vec["documents"][0], vec["metadatas"][0], vec["distances"][0]
        )
    }

    if not settings.USE_BM25:
        return chroma_client.search(
            query, hero_id=hero_id, patches=patches, top_k=n, collection_name=collection_name
        )

    bm25_hits = search(
        query, hero_id=hero_id, patches=patches, top_k=settings.BM25_TOP_K, collection_name=collection_name
    )
    bm25_ids = [h[0] for h in bm25_hits]
    bm25_by_id = {h[0]: (h[1], h[2], h[3]) for h in bm25_hits}

    fused = rrf_fuse([vec_ids, bm25_ids])
    out: list[Evidence] = []
    for doc_id, _score in fused[:n]:
        if doc_id in vec_by_id:
            doc, meta, dist = vec_by_id[doc_id]
            sim = 1.0 - float(dist)
        else:
            doc, meta, _bs = bm25_by_id[doc_id]
            sim = None
        out.append(
            Evidence(
                kind="vector",
                content=doc,
                hero_ids=list(meta.get("hero_ids", [])),
                relation=None,
                patch=meta.get("patch"),
                source=meta.get("source_type", "official"),
                source_url=meta.get("source_url"),
                score=sim,
            )
        )
    return out
