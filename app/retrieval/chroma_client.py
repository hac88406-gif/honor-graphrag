"""Chroma 向量检索封装（规格书 4.6）。

两道过滤缺一不可（4.6 已裁定）：
  1. **patch 版本过滤** —— 标量字段用 `$in`，窗口取 config.PATCH_WINDOW（1.9 统一口径）；
  2. **hero_ids 元数据过滤** —— **列表字段必须用 `$contains`**。

为什么 hero 过滤不能省（4.6）：不加过滤时问「铠怎么打」会把「貂蝉怎么打」的攻略一起召回，
因为两篇都是游戏术语、语义相似度很高。纯向量检索在专有名词密度高的中文文本上，
元数据过滤比模型选择重要得多。

为什么算子必须区分（4.6 v1.4 修正）：chromadb 1.5.9 下对**列表字段**用 `$in` 会**静默返回空**——
不报错、不警告，结果和「知识库确实没收录这个英雄」长得一样。故本模块统一用 `$contains`，
并由 tests/unit/test_retrieval_chroma.py 固化 `$in` 空 / `$contains` 有命中的差异。

collection 获取**必须**走 app/utils/chroma.py 的 get_collection()（4.6 强制项），
不得裸取——裸取会回退默认 ONNX EF，导致查询向量与写入向量不同源、召回静默失效。
"""
from __future__ import annotations

import logging

from app.config import settings
from app.schemas.chat import Evidence
from app.utils.chroma import COLLECTION_NAME, get_collection

logger = logging.getLogger(__name__)


class VectorStoreUnavailable(RuntimeError):
    """Chroma collection 不存在或查询失败。"""


def build_where(hero_id: str | None = None, patches: list[str] | None = None) -> dict | None:
    """构造 where 子句：标量 patch 用 `$in`，列表 hero_ids 用 `$contains`（4.6）。"""
    clauses: list[dict] = []
    if patches:
        clauses.append({"patch": {"$in": list(patches)}})
    if hero_id:
        clauses.append({"hero_ids": {"$contains": hero_id}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def raw_query(
    query: str,
    *,
    hero_id: str | None = None,
    patches: list[str] | None = None,
    top_k: int | None = None,
    collection_name: str = COLLECTION_NAME,
) -> dict:
    """底层查询，返回 chromadb 原始结果（测试用它断言 ids/distances）。"""
    try:
        collection = get_collection(collection_name)
    except Exception as e:
        raise VectorStoreUnavailable(f"collection '{collection_name}' 不可用：{e}") from e

    n = top_k or settings.VECTOR_TOP_K
    where = build_where(hero_id, settings.PATCH_WINDOW if patches is None else patches)
    try:
        return collection.query(
            query_texts=[query],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        raise VectorStoreUnavailable(f"Chroma 查询失败：{e}") from e


def search(
    query: str,
    *,
    hero_id: str | None = None,
    patches: list[str] | None = None,
    top_k: int | None = None,
    collection_name: str = COLLECTION_NAME,
) -> list[Evidence]:
    """向量检索 -> Evidence 列表。score = 1 - cosine_distance（越大越相关）。"""
    res = raw_query(
        query, hero_id=hero_id, patches=patches, top_k=top_k, collection_name=collection_name
    )
    out: list[Evidence] = []
    for cid, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        out.append(
            Evidence(
                kind="vector",
                content=doc,
                hero_ids=list(meta.get("hero_ids", [])),
                relation=None,
                patch=meta.get("patch"),
                source=meta.get("source_type", "official"),
                source_url=meta.get("source_url"),
                score=1.0 - float(dist),
            )
        )
        logger.debug("vector hit %s dist=%.4f", cid, dist)
    return out
