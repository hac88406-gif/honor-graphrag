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

from functools import lru_cache
from pathlib import Path

from app.config import settings

# app/utils/chroma.py -> app/utils -> app -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COLLECTION_NAME = "guides"


class BgeEmbeddingFunction:
    """实现 chromadb 1.x 的 EmbeddingFunction 协议（__call__/name/get_config/build_from_config）。"""

    def __init__(self, model, model_ref: str) -> None:
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
        return load_embedding_function()


@lru_cache(maxsize=1)
def load_embedding_function() -> BgeEmbeddingFunction:
    """规格书 1.3：bge-large-zh-v1.5，本地 CPU。优先加载本地目录，避免运行时联网。

    进程内缓存：模型约 1.2GB，每次 get_collection() 都新建 SentenceTransformer 会让
    单次检索耗时以十秒计（M2 检索层每条查询都会取 collection）。缓存的是**同一个
    EF 实例**，不改变「必须显式传入 EF」这一契约。
    """
    from sentence_transformers import SentenceTransformer

    local_dir = PROJECT_ROOT / settings.EMBEDDING_MODEL_DIR
    model_ref = str(local_dir) if local_dir.exists() else settings.EMBEDDING_MODEL
    if not local_dir.exists():
        print(f"[chroma] 本地模型目录不存在（{local_dir}），回退到 HF 名 {model_ref}")
    model = SentenceTransformer(model_ref, device=settings.EMBEDDING_DEVICE)
    return BgeEmbeddingFunction(model, model_ref)


def get_client():
    """嵌入式 PersistentClient（零外部依赖）。"""
    import chromadb

    return chromadb.PersistentClient(path=str(PROJECT_ROOT / settings.CHROMA_PERSIST_DIR))


def get_collection(name: str = COLLECTION_NAME):
    """唯一允许的 collection 获取方式：**显式**传入 bge embedding function。

    不要改成 `client.get_collection(name)`——裸取会回退默认 ONNX EF，静默改变向量空间。
    """
    return get_client().get_collection(name=name, embedding_function=load_embedding_function())


def corpus_metadata(meta: dict, keys: list[str]) -> dict:
    """语料 front-matter -> chromadb 可接受的 metadata（**入库侧的唯一转换点**）。

    chromadb 1.5.9 **拒绝空列表值**：
    `ValueError: Expected metadata list value for key 'hero_ids' to be non-empty in add.`

    而「不带英雄的通用语料」在语义上是**合法且必要**的：版本理解 / 通用意识类文档不属于
    任何单个英雄，`TIER_META` 意图本就不带 hero 槽位、检索时只按 patch 窗口过滤
    （见 app/agent/nodes/vector_search.py），这类文档照样能被召回。
    故空列表**省略该键**而不是写空值：省略后 `{"hero_ids": {"$contains": id}}` 天然不匹配，
    语义恰好等于「与任何英雄都无关联」。

    为什么放在这里：上传端点（app/api/docs.py）与全库重建（scripts/init_chroma.py）
    是**两个**入库写入方，若各自处理这条约束就会再次分叉成两个口径。
    """
    out: dict = {}
    for k in keys:
        v = meta[k]
        if isinstance(v, list) and not v:
            continue
        out[k] = v
    return out
