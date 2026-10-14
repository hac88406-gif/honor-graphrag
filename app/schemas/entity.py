"""实体链接输出结构（规格书 4.3）。

字段与枚举值原样照搬规格书 4.3 的 LinkedEntity，不增删。
`entity_type` 五值与 `method` 四值都是封闭枚举——M2 的意图/槽位抽取依赖它们做分支，
私自扩展会让下游出现未定义的取值。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LinkedEntity(BaseModel):
    raw: str                  # 用户原文
    canonical_id: str | None = None   # 图谱规范 ID，未识别为 None
    canonical_name: str | None = None
    entity_type: Literal["hero", "item", "inscription", "role", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)   # 0~1
    method: Literal["exact", "alias", "fuzzy", "none"]
