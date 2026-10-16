"""Chroma 向量库初始化与幂等导入（规格书 4.6 / 6.4 阶段一）。

把 data/guides/*.md 的长文本语料切分后写入嵌入式 Chroma 的 "guides" collection。

要点（均来自规格书 4.6，非自定）：
  - collection 名 "guides"；ids = doc_id + "#" + chunk_index
  - documents = chunk 正文；metadatas 含 doc_id/hero_ids/topic/patch/source_url/
    source_type/publish_date/chunk_index/data_source 九个字段
  - 切分：**按语义段落**（标题 / 段落 / 列表项为语义单元），目标 300~500 字、重叠 100 字，
    不按固定 token 硬切
  - Embedding：规格书 1.3 选型 BAAI/bge-large-zh-v1.5（本地 CPU，L2 归一化后余弦等价）

幂等：每次运行先删除同名 collection 再重建，保证重复执行 count 不漂移、无陈旧 chunk。
（对比 Neo4j 侧的 MERGE 幂等：Chroma 无 upsert-by-content，删库重建是最干净的等幂方式。）

用法：
  python scripts/init_chroma.py --dry-run   # 只切分、打印统计，不写库、不加载模型
  python scripts/init_chroma.py             # 建库并导入，打印 collection.count()
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml  # noqa: E402

from app.utils.chroma import (  # noqa: E402
    COLLECTION_NAME,
    corpus_metadata,
    get_client,
    load_embedding_function,
)

# 切分实现**不在本脚本内**：与 POST /api/docs/upload 共用 app/utils/text_split.py，
# 避免「重建出来的 chunk」与「接口写进去的 chunk」出现两套口径（见该模块 docstring）。
from app.utils.text_split import pack, split_atoms  # noqa: E402

GUIDES_DIR = PROJECT_ROOT / "data" / "guides"

META_KEYS = [
    "doc_id", "hero_ids", "topic", "patch",
    "source_url", "source_type", "publish_date", "data_source",
]


# ---------------------------------------------------------------- 解析

def parse_guide(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name} 缺少 YAML front-matter")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    missing = [k for k in META_KEYS if k not in meta]
    if missing:
        raise ValueError(f"{path.name} metadata 缺字段：{missing}")
    return meta, body


def build_records() -> tuple[list[str], list[str], list[dict], dict]:
    ids, docs, metas = [], [], []
    per_doc: dict[str, int] = {}
    for path in sorted(GUIDES_DIR.glob("*.md")):
        meta, body = parse_guide(path)
        chunks = pack(split_atoms(body))
        if not chunks:
            raise ValueError(f"{path.name} 切分后为空")
        per_doc[meta["doc_id"]] = len(chunks)
        for idx, chunk in enumerate(chunks):
            ids.append(f"{meta['doc_id']}#{idx}")
            docs.append(chunk)
            md = corpus_metadata(meta, META_KEYS)
            md["chunk_index"] = idx
            metas.append(md)
    return ids, docs, metas, per_doc


# ---------------------------------------------------------------- Embedding
# EF 加载与 collection 获取统一走 app/utils/chroma.py（规格书 4.6 强制项），
# 本脚本从该模块 import，不再自行定义，避免出现第二个 EF 来源。


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只切分统计，不写库")
    args = ap.parse_args()

    if not GUIDES_DIR.exists() or not glob.glob(str(GUIDES_DIR / "*.md")):
        raise SystemExit("data/guides 下没有语料，请先运行 scripts/build_guides.py")

    ids, docs, metas, per_doc = build_records()
    sizes = sorted(len(d) for d in docs)
    print(f"[chroma] 语料 {len(per_doc)} 篇 -> chunk {len(ids)} 条")
    print(f"[chroma] 每篇 chunk 数：{per_doc}")
    print(f"[chroma] chunk 字数 min/median/max = "
          f"{sizes[0]}/{sizes[len(sizes) // 2]}/{sizes[-1]}")

    if args.dry_run:
        print("[chroma] dry-run 结束（未写库、未加载模型）")
        return 0

    client = get_client()
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
        print(f"[chroma] 已删除旧 collection {COLLECTION_NAME}（幂等重建）")

    ef = load_embedding_function()
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        configuration={"hnsw": {"space": "cosine"}},
    )
    collection.add(ids=ids, documents=docs, metadatas=metas)

    total = collection.count()
    print(f"[chroma] collection.count() = {total}")
    if total < 100:
        raise SystemExit(f"语料 chunk 数 {total} < 100，未达 M1b 要求")

    # 抽查：按 hero_ids 过滤 + 语义查询，确认写入可被检索。
    # hero_ids 是列表字段：chromadb 1.5.9 下 $in 对列表返回空，须用 $contains（见 DECISIONS.md）。
    probe = collection.query(
        query_texts=["貂蝉怎么出装"],
        n_results=2,
        where={"hero_ids": {"$contains": "141"}},
    )
    print("[chroma] 抽查 query('貂蝉怎么出装', hero_ids=141) 命中：")
    for cid, doc in zip(probe["ids"][0], probe["documents"][0]):
        print(f"  - {cid}: {doc[:40].replace(chr(10), ' ')}...")

    # 算子差异对照（规格书 4.6 静默失败陷阱一）：列表字段用 $in 会静默返回空。
    wrong = collection.query(
        query_texts=["貂蝉怎么出装"],
        n_results=2,
        where={"hero_ids": {"$in": ["141"]}},
    )
    print(f"[chroma] 对照：$in 命中 {len(wrong['ids'][0])} 条（预期 0），"
          f"$contains 命中 {len(probe['ids'][0])} 条（预期 >0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
