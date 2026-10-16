"""POST /api/docs/upload：上传攻略文本并入库（规格书 5.2，M7 归属）。

规格书 5.2 把该端点定为「📌 归 M7（与 C1 语料的版权声明一并处理）」。两者能一并处理，
是因为**上传内容的处理方式与 C1 完全同构**：文本写盘到 `data/guides/upload-*.md`
但**不入版本库**（`.gitignore` 已排除该模式），只进本地 Chroma。于是「仓库已公开」
与「用户上传的第三方文本可能涉版权」不再冲突 —— README 的数据声明只需说一次，
C1 与上传走的是同一条规则。

三条口径约束（本项目反复踩「同一件事两个口径」的坑，这里刻意不制造第二个）：

1. **切分**：复用 `app/utils/text_split.py`，与 `scripts/init_chroma.py` 同一实现。
2. **先落盘、再入库**：先写 `data/guides/{doc_id}.md`（YAML front-matter 字段与
   init_chroma 的 `META_KEYS` 一致），再索引到 Chroma。这样 `scripts/init_chroma.py`
   删库重建时上传内容**会被一并重建**，不会「重建一次就消失」。反过来（只写 Chroma
   不写盘）上传就成了第二个数据源，重建即丢；故落盘是**先**做的，落盘成功而入库失败时
   只需重跑 init_chroma.py 即可补齐，不需要重新上传。
3. **幂等**：同一 `doc_id` 重复上传 = **整体替换**（先删该 doc_id 的全部 chunk 再写）。
   Chroma 无 upsert-by-content，「按 doc_id 替换」是最干净的等幂语义
   （与 init_chroma 的「删库重建」同理）。

**鉴权：不做，且这是有意的。** 本服务是本地演示（绑定 127.0.0.1；规格书 3.3 把登录列为
非目标），端点只服务本机。故只做输入校验与体积上限，不引入 token 机制 —— 一个形同虚设的
鉴权比没有鉴权更危险，它会让人误以为已经安全。若将来要对外暴露，必须先补鉴权与配额。

错误码口径：**422 = 表单缺字段**（FastAPI 对必填 `Form` 的标准行为，即「metadata 没带全」）；
**400 = 字段值或文件内容不合法**；**413 = 超过体积上限**；**503 = Chroma 不可用**。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.utils.chroma import corpus_metadata, get_collection
from app.utils.text_split import split_document

router = APIRouter(tags=["docs"])

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GUIDES_DIR = PROJECT_ROOT / "data" / "guides"

# 单篇上限 1 MiB：一篇攻略正文实测 500~1500 字，留三个数量级余量即可；
# 再大就不是「攻略文本」而是数据集导入，那属于另一个端点（v1 不做）。
MAX_UPLOAD_BYTES = 1024 * 1024

# doc_id 必须命中 .gitignore 的 `data/guides/upload-*.md`：上传内容是第三方文本，
# 与 C1 同理不得进入公开版本库。用命名前缀把这条约束变成**可校验的硬规则**，
# 而不是靠「记得别提交」。
DOC_ID_RE = re.compile(r"^upload-[a-z0-9][a-z0-9._-]{0,63}$")
PATCH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HERO_ID_RE = re.compile(r"^\d+$")

SOURCE_TYPES = ("official", "community")
# 取值与现有语料保持一致（data/guides 实测）：C1 官方原文 = real，C2 LLM 撰写 = llm_assisted
DATA_SOURCES = ("real", "llm_assisted")

META_KEYS = [
    "doc_id", "hero_ids", "topic", "patch",
    "source_url", "source_type", "publish_date", "data_source",
]


def _bad(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def patch_hint() -> str:
    """报错信息里带上当前版本窗口，省得调用方自己翻 config。"""
    from app.config import settings

    return "/".join(settings.PATCH_WINDOW)


def _validate_metadata(
    *, doc_id: str, topic: str, patch: str, source_url: str,
    source_type: str, data_source: str, publish_date: str, hero_ids_raw: str,
) -> list[str]:
    """校验 metadata，返回解析后的 hero_ids（列表）。任何一项不合法都直接 400。"""
    if not DOC_ID_RE.match(doc_id):
        raise _bad(
            "doc_id 必须形如 upload-xxx（小写字母/数字/点/下划线/连字符，≤72 字符）。"
            "前缀 upload- 同时决定了落盘文件名命中 .gitignore，故不可放宽。"
        )
    if not topic or len(topic) > 40:
        raise _bad("topic 必填且不超过 40 字")
    if not PATCH_RE.match(patch):
        raise _bad(f"patch 必须形如 YYYY-MM（当前语料口径为 {patch_hint()}），收到：{patch!r}")
    if not source_url.startswith(("http://", "https://")):
        raise _bad("source_url 必填且必须是 http/https 开头的可追溯地址（依据要能点开核对）")
    if source_type not in SOURCE_TYPES:
        raise _bad(f"source_type 只能是 {' / '.join(SOURCE_TYPES)}，收到：{source_type!r}")
    if data_source not in DATA_SOURCES:
        raise _bad(f"data_source 只能是 {' / '.join(DATA_SOURCES)}，收到：{data_source!r}")
    if not DATE_RE.match(publish_date):
        raise _bad(f"publish_date 必填且必须形如 YYYY-MM-DD，收到：{publish_date!r}")

    hero_ids = [h.strip() for h in hero_ids_raw.split(",") if h.strip()]
    bad = [h for h in hero_ids if not HERO_ID_RE.match(h)]
    if bad:
        raise _bad(f"hero_ids 须为逗号分隔的数字 ename，非法项：{bad}")
    return hero_ids


def _display_path(path: Path) -> str:
    """返回给调用方的可读路径。

    正常情况给仓库内相对路径（`data/guides/upload-xxx.md`）；若落盘目录被指到仓库之外
    （测试用临时目录），退化为绝对路径 —— 不能让一个「为了好读」的转换把请求打成 500。
    """
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _front_matter(meta: dict) -> str:
    """与 scripts/build_guides.py 的 yaml_block 同格式（YAML 里 list 用 JSON 流式写法）。"""
    lines = ["---"]
    for k in META_KEYS:
        lines.append(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


@router.post("/docs/upload")
async def upload_doc(
    file: UploadFile = File(..., description="攻略正文（UTF-8 文本）"),
    doc_id: str = Form(..., description="文档唯一键，须以 upload- 开头；重复上传=整体替换"),
    topic: str = Form(..., description="主题，如「对线思路」"),
    patch: str = Form(..., description="版本，形如 2026-10"),
    source_url: str = Form(..., description="来源地址，须可点开核对"),
    source_type: str = Form(..., description="official / community"),
    data_source: str = Form(..., description="real（原文照录）/ llm_assisted（模型撰写）"),
    publish_date: str = Form(..., description="发布日期，形如 2026-10-16"),
    hero_ids: str = Form("", description="关联英雄 ename，逗号分隔，可空"),
) -> dict:
    hero_id_list = _validate_metadata(
        doc_id=doc_id, topic=topic, patch=patch, source_url=source_url,
        source_type=source_type, data_source=data_source,
        publish_date=publish_date, hero_ids_raw=hero_ids,
    )

    raw = await file.read()
    if not raw:
        raise _bad("上传内容为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件 {len(raw)} 字节超过上限 {MAX_UPLOAD_BYTES} 字节（1 MiB）",
        )
    try:
        # 只收 UTF-8：官方页面那套「GBK 静默乱码」的教训说明**猜编码**会把错误藏起来
        # （按 UTF-8 解 GBK 不抛异常、只产出乱码）。上传侧选择直接报错，让调用方自己转码。
        body = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError as e:
        raise _bad(f"文件必须是 UTF-8 编码（GBK 等请先转码，避免静默乱码）：{e}") from e
    if not body:
        raise _bad("上传内容为空白（去掉首尾空白后无正文）")

    chunks = split_document(body)
    if not chunks:
        raise _bad("切分后无有效 chunk（正文可能只有空白或分隔符）")

    meta = {
        "doc_id": doc_id,
        "hero_ids": hero_id_list,
        "topic": topic,
        "patch": patch,
        "source_url": source_url,
        "source_type": source_type,
        "publish_date": publish_date,
        "data_source": data_source,
    }

    # 先落盘（权威源 = 文件），再入库（派生 = Chroma）。顺序不可颠倒，理由见模块 docstring 第 2 条。
    GUIDES_DIR.mkdir(parents=True, exist_ok=True)
    path = GUIDES_DIR / f"{doc_id}.md"
    path.write_text(_front_matter(meta) + "\n\n" + body + "\n", encoding="utf-8")

    try:
        collection = get_collection()
        replaced = bool(collection.get(where={"doc_id": doc_id})["ids"])
        if replaced:
            collection.delete(where={"doc_id": doc_id})
        collection.add(
            ids=[f"{doc_id}#{i}" for i in range(len(chunks))],
            documents=chunks,
            # 经 corpus_metadata 转换：空 hero_ids 会**省略该键**（chromadb 拒绝空列表值），
            # 与 scripts/init_chroma.py 走同一转换点，保证「接口写入」与「重建」metadata 一致。
            metadatas=[
                {**corpus_metadata(meta, META_KEYS), "chunk_index": i}
                for i in range(len(chunks))
            ],
        )
        total = collection.count()
    except Exception as e:  # noqa: BLE001 - 统一转成 503，不把内部异常细节漏给调用方
        logger.exception("上传入库失败：doc_id=%s", doc_id)
        raise HTTPException(
            status_code=503,
            detail=(
                f"文件已写入 {_display_path(path)}，但索引失败（{type(e).__name__}）：{e}。"
                "重跑 scripts/init_chroma.py 即可把已落盘的内容补齐，无需重新上传。"
            ),
        ) from e

    logger.info("语料已上传：doc_id=%s chunks=%d replaced=%s", doc_id, len(chunks), replaced)
    return {
        "doc_id": doc_id,
        "chunks": len(chunks),
        "replaced": replaced,
        "path": _display_path(path),
        "collection_count": total,
    }
