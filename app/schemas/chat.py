"""问答接口数据契约（规格书 5.1，逐字段照搬，不得简化）。

M2 阶段只产出 `Evidence`（检索层输出结构）；其余模型为 5.1 完整契约的一部分，
在 M2 一次落齐，避免 M3/M4 再改动契约导致评测脚本返工。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.entity import LinkedEntity


class ChatRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=500)
    stream: bool = True


class Evidence(BaseModel):
    kind: Literal["graph", "vector"]
    content: str                    # 图谱: 关系描述文本; 向量: chunk 正文
    hero_ids: list[str] = []
    relation: str | None = None     # 图谱: COUNTERS / SYNERGIZES ...
    patch: str | None = None
    source: str                     # 来源标识
    source_url: str | None = None
    score: float | None = None      # 向量: 相似度


class Citation(BaseModel):
    index: int
    kind: Literal["graph", "vector"]
    label: str                      # 展示给用户的一行来源说明
    url: str | None = None
    patch: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    type: Literal["answer", "low_confidence", "reject", "clarify"]
    answer: str
    citations: list[Citation] = []
    confidence: float
    intent: str
    entities: list[LinkedEntity] = []
    clarify_options: list[str] = []   # type == "clarify" 时填充
    debug: dict | None = None         # 仅在 DEBUG=1 时返回
