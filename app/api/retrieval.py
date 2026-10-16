"""补丁 P1 检索端点（`app/api/retrieval.py`）：`POST /api/retrieval/search`（P1-2，只读）。

**作用**：向量 + BM25 混合检索，返回命中的攻略**原文片段**（不是答案）。

**为什么它不是「又一个问答端点」**：`/api/chat/sync` 是粗粒度入口，内部顺带跑了
图谱 + 检索 + 生成。项目二需要的是「只搜攻略」这个**细粒度动作**，用于包成 MCP 工具，
并且它的两条核心验收（「参数超限被拒」需要可调数值参数、「工具选择正确率」需要
至少两个语义相近的工具）都依赖本端点提供的 `top_k` 与图谱端点。

**必须直接调用 `bm25.hybrid_search`**（契约 §2-2 强制项）：在新端点里自己拼一次
「向量检索 + BM25 + RRF 融合」就是第二套实现，两条召回路径迟早会分叉。`hero` 消歧后
转 `hero_id` 传给它，过滤与融合都在既有实现里，本层不做任何检索逻辑。

**依赖不可用时 503，不降级**（契约 §5-1，与 P1-1 同口径）：`hybrid_search` 的首个动作
就是向量检索，Chroma 不可用会以 `VectorStoreUnavailable` 抛出。若在这里吞掉它返回
`200 + items: []`，调用方无法区分「知识库确实没这条」与「向量库挂了」。
"""
from __future__ import annotations

from typing import Final

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api._contract import bad, link_one_hero, unavailable, validate_int_range, validate_patches
from app.retrieval import bm25
from app.retrieval.chroma_client import VectorStoreUnavailable

router = APIRouter(tags=["retrieval"])

QUERY_MIN_CHARS: Final[int] = 1
QUERY_MAX_CHARS: Final[int] = 500
TOP_K_MIN: Final[int] = 1
TOP_K_MAX: Final[int] = 20


class RetrievalSearchRequest(BaseModel):
    query: str = Field(..., description=f"检索问句，{QUERY_MIN_CHARS}~{QUERY_MAX_CHARS} 字")
    hero: str | None = Field(None, description="用于元数据过滤；给了则同样走 entity_linking 消歧")
    top_k: int | None = Field(None, description=f"{TOP_K_MIN}~{TOP_K_MAX}，默认 VECTOR_TOP_K")
    patches: list[str] | None = Field(None, description="版本窗口，默认 settings.PATCH_WINDOW")


def _validate_query(query: str) -> str:
    """长度是**接口契约**而不是建议：过短检索不出东西，过长会把整篇文档当查询。

    注意分工 —— 字段缺失由 FastAPI 判 422（请求体形状），本函数只管取值（400）。
    """
    if not query.strip():
        raise bad("query_empty", "query 不能为空（去掉首尾空白后无内容）")
    if len(query) > QUERY_MAX_CHARS:
        raise bad("query_too_long", f"query 不能超过 {QUERY_MAX_CHARS} 字，收到 {len(query)} 字")
    return query


@router.post("/retrieval/search")
def retrieval_search(req: RetrievalSearchRequest) -> dict:
    """P1-2：混合检索攻略原文，返回 `Evidence` 列表（`kind="vector"`）。"""
    query = _validate_query(req.query)
    top_k = validate_int_range(req.top_k, TOP_K_MIN, TOP_K_MAX, "top_k")
    patches = validate_patches(req.patches)
    # hero 可选：不给则不加元数据过滤（版本理解 / 通用意识类语料本就不属于任何单个英雄）
    hero = link_one_hero(req.hero) if req.hero is not None else None

    # 只透传显式给了的参数：top_k / patches 缺省由 hybrid_search 自己落到 config
    kwargs: dict = {}
    if hero is not None:
        kwargs["hero_id"] = hero.canonical_id
    if top_k is not None:
        kwargs["top_k"] = top_k
    if patches is not None:
        kwargs["patches"] = patches

    try:
        items = bm25.hybrid_search(query, **kwargs)
    except VectorStoreUnavailable as e:
        raise unavailable("vector_store_unavailable", f"Chroma 不可用，混合检索失败：{e}") from e

    return {
        "query": query,
        "hero": (
            {"id": hero.canonical_id, "name": hero.canonical_name, "matched_by": hero.method}
            if hero is not None
            else None
        ),
        "count": len(items),
        "items": [e.model_dump() for e in items],
    }
