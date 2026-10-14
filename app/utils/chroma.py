"""Chroma collection 的统一获取入口（规格书 4.6「第二个静默失败陷阱」强制项）。

为什么必须统一：Chroma 持久化后重新打开 collection 时，若不显式传入创建时用的
embedding function，会回退到默认的 ONNX 模型（all-MiniLM-L6-v2）并尝试联网下载。
后果是**查询向量与写入向量来自两个不同的模型** → 相似度无意义 → 召回失效或为空，
且不报错。这与「算子写错」是同一类失败：表现为「检索不到」，而你会以为「知识库没数据」。

因此全项目**禁止**任何地方直接 `chroma_client.get_collection("guides")`，
一律走本模块的 `get_collection()`——它内部固定传入 bge-large-zh-v1.5 的 embedding function。
（该封装及原因已登记于 DECISIONS.md 2026-10-14 条。）
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings

# app/utils/chroma.py -> app/utils -> app -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COLLECTION_NAME = "guides"


def load_embedding_function():
    """规格书 1.3：bge-large-zh-v1.5，本地 CPU。优先加载本地目录，避免运行时联网。"""
    from sentence_transformers import SentenceTransformer

    local_dir = PROJECT_ROOT / settings.EMBEDDING_MODEL_DIR
    model_ref = str(local_dir) if local_dir.exists() else settings.EMBEDDING_MODEL
    if not local_dir.exists():
        print(f"[chroma] 本地模型目录不存在（{local_dir}），回退到 HF 名 {model_ref}")
    model = SentenceTransformer(model_ref, device=settings.EMBEDDING_DEVICE)

    class BgeEmbeddingFunction:
        """实现 chromadb 1.x 的 EmbeddingFunction 协议（__call__/name/get_config/build_from_config）。"""

        def __init__(self) -> None:
            self._model = model
            self._ref = model_ref

        def __call__(self, input):  # noqa: A002 - 协议固定形参名
            vecs = self._model.encode(
                list(input), normalize_embeddings=True, convert_to_numpy=True
            )
            return vecs.tolist()

        def embed_query(self, input):  # noqa: A002
            # bge 检索侧建议加指令前缀；M2 检索层细化，这里先与入库同分布
            return self.__call__(input)

        def default_space(self) -> str:
            return "cosine"

        def supported_spaces(self) -> list[str]:
            return ["cosine", "l2", "ip"]

        @staticmethod
        def name() -> str:
            return "bge-large-zh-v1.5"

        def get_config(self) -> dict:
            return {"model_ref": self._ref, "device": settings.EMBEDDING_DEVICE}

        @staticmethod
        def build_from_config(config: dict):
            return BgeEmbeddingFunction()

    return BgeEmbeddingFunction()


def get_client():
    """嵌入式 PersistentClient（零外部依赖）。"""
    import chromadb

    return chromadb.PersistentClient(path=str(PROJECT_ROOT / settings.CHROMA_PERSIST_DIR))


def get_collection(name: str = COLLECTION_NAME):
    """唯一允许的 collection 获取方式：**显式**传入 bge embedding function。

    不要改成 `client.get_collection(name)`——裸取会回退默认 ONNX EF，静默改变向量空间。
    """
    return get_client().get_collection(name=name, embedding_function=load_embedding_function())
