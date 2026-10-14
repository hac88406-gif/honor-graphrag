"""Pydantic 数据契约（规格书 4.3 实体链接 / 5.1 接口契约）。

字段与枚举值严格照规格书写，不得增删或改名——5.1 明确「必须严格实现，不得简化」。
"""
from app.schemas.chat import ChatRequest, ChatResponse, Citation, Evidence
from app.schemas.entity import LinkedEntity

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "Citation",
    "Evidence",
    "LinkedEntity",
]
