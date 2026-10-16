"""M7 集成测试 —— `POST /api/docs/upload`（规格书 5.2）。

断言重点不是 HTTP 200：**「上传成功」这句话本身没有价值，有价值的是内容真的进了知识库**。
故在线用例断言三件事：
  1. 落盘文件的 front-matter 能被 `scripts/init_chroma.py` 的 `parse_guide` 解析 ——
     否则 `scripts/init_chroma.py` 重建时会直接抛错，上传内容「重建即丢」；
  2. 该 doc 的 chunk 真在 Chroma 里，且**按 hero_ids 过滤能被召回**（用自身文本查询，
     余弦相似度应为 1.0 → 必须 top-1）；
  3. 同 `doc_id` 二次上传是**替换**（count 不涨、ids 不变），不是叠加。

离线用例（不依赖 Chroma / Neo4j）覆盖 metadata 缺失与非法、体积上限、编码，
它们都在 `_validate_metadata` 或读文件阶段就返回，不会走到 `get_collection()`。

Chroma 用例走 `require_chroma` 门禁（tests/conftest.py）：开发模式 skip，验收模式 fail。
"""

from __future__ import annotations

import httpx
import pytest

from app.api import docs as docs_mod
from init_chroma import parse_guide

DOC_ID = "upload-ut-diaochan"

VALID_FORM = {
    "doc_id": DOC_ID,
    "topic": "对线思路",
    "patch": "2026-10",
    "source_url": "https://pvp.qq.com/web201605/herodetail/diaochan.shtml",
    "source_type": "community",
    "data_source": "real",
    "publish_date": "2026-10-16",
    "hero_ids": "141",
}

BODY = (
    "貂蝉对线期靠被动印记消耗，一技能缘·心结可远程叠层。"
    "面对张良这类硬控英雄要留二技能保命，因为位移被打断后无法用消失规避后续技能。"
    "团战中应等对方交出关键控制再入场，用大招法阵缩短冷却，把持续输出窗口拉到最长。"
)


@pytest.fixture
async def client():
    """ASGI 直连客户端（同 test_session_api 的做法，不启真实端口）。"""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def guides_tmp(tmp_path, monkeypatch):
    """把落盘目录指到临时目录：上传用例不得污染仓库的 data/guides。"""
    monkeypatch.setattr(docs_mod, "GUIDES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def clean_doc_id():
    """用例前后清掉本测试用的 doc_id，避免污染真实 collection 影响其它用例。"""
    from app.utils.chroma import get_collection

    def _purge() -> None:
        try:
            get_collection().delete(where={"doc_id": DOC_ID})
        except Exception:  # noqa: BLE001 - 未建库时无需清理
            pass

    _purge()
    yield
    _purge()


# ---------------------------------------------------------------- 离线：metadata 校验

async def test_missing_required_metadata_returns_422(client):
    """必填 metadata 缺失 → 422（规格书 5.2「必须带 metadata」由 FastAPI 表单约束落地）。"""
    form = {k: v for k, v in VALID_FORM.items() if k != "patch"}
    r = await client.post(
        "/api/docs/upload", data=form, files={"file": ("g.md", BODY, "text/markdown")}
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("field", "bad_value", "expected", "why"),
    [
        ("doc_id", "c3-no-prefix", 400, "doc_id 缺 upload- 前缀则落盘文件不被 .gitignore 覆盖"),
        ("doc_id", "upload-UPPER", 400, "大写不入 .gitignore 模式"),
        ("patch", "2026/10", 400, "patch 必须是 YYYY-MM，否则版本过滤窗口匹配不上"),
        ("patch", "v2026-10", 400, "同上"),
        ("source_url", "ftp://pvp.qq.com/x", 400, "来源必须可点开核对，非 http/https 一律拒"),
        ("source_url", "diaochan.shtml", 400, "相对路径无法追溯"),
        ("source_type", "third_party", 400, "source_type 取值封闭"),
        ("data_source", "generated", 400, "data_source 取值封闭"),
        ("publish_date", "2026-10", 400, "publish_date 必须到日"),
        ("hero_ids", "141,abc", 400, "hero_ids 必须是数字 ename"),
        ("topic", "x" * 41, 400, "topic 有长度上限，防把正文塞进 metadata"),
        ("topic", "", 422, "空串被 FastAPI 视同「没带」，与缺字段同为 422"),
    ],
)
async def test_invalid_metadata_is_rejected(client, field, bad_value, expected, why):
    form = {**VALID_FORM, field: bad_value}
    r = await client.post(
        "/api/docs/upload", data=form, files={"file": ("g.md", BODY, "text/markdown")}
    )
    assert r.status_code == expected, (
        f"{field}={bad_value!r} 应返回 {expected}（{why}），实际 {r.status_code}"
    )


async def test_empty_file_returns_400(client):
    r = await client.post(
        "/api/docs/upload", data=VALID_FORM, files={"file": ("g.md", b"", "text/markdown")}
    )
    assert r.status_code == 400


async def test_whitespace_only_file_returns_400(client):
    r = await client.post(
        "/api/docs/upload",
        data=VALID_FORM,
        files={"file": ("g.md", b"   \n\n\t  ", "text/markdown")},
    )
    assert r.status_code == 400


async def test_non_utf8_file_returns_400(client):
    """GBK 字节必须被明确拒绝：官方页面那套「按 UTF-8 解 GBK 不报错、只出乱码」的静默失败
    不能在上传侧重演 —— 猜编码会把错误藏起来。"""
    gbk = "貂蝉对线思路：靠被动印记消耗。".encode("gbk")
    r = await client.post(
        "/api/docs/upload", data=VALID_FORM, files={"file": ("g.md", gbk, "text/markdown")}
    )
    assert r.status_code == 400
    assert "UTF-8" in r.json()["detail"]


async def test_oversize_file_returns_413(client):
    r = await client.post(
        "/api/docs/upload",
        data=VALID_FORM,
        files={"file": ("g.md", b"x" * (docs_mod.MAX_UPLOAD_BYTES + 1), "text/markdown")},
    )
    assert r.status_code == 413


# ---------------------------------------------------------------- 在线：落盘 + 入库 + 幂等

async def test_upload_writes_rebuildable_file_and_indexes_chunks(
    client, require_chroma, guides_tmp, clean_doc_id
):
    """上传后：文件可被重建脚本解析 + chunk 真在 Chroma 里且可被 hero 过滤召回。"""
    require_chroma()

    r = await client.post(
        "/api/docs/upload", data=VALID_FORM, files={"file": ("g.md", BODY, "text/markdown")}
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["chunks"] >= 1
    assert payload["replaced"] is False
    assert payload["path"] == f"data/guides/{DOC_ID}.md" or payload["path"].endswith(f"{DOC_ID}.md")

    # 1) 落盘文件必须能被 init_chroma 的解析器读出来 —— 否则重建时直接抛错
    path = guides_tmp / f"{DOC_ID}.md"
    assert path.exists(), "上传必须先落盘（权威源是文件，Chroma 只是派生）"
    meta, body = parse_guide(path)
    assert meta["doc_id"] == DOC_ID
    assert meta["hero_ids"] == ["141"]
    assert meta["source_type"] == "community"
    assert meta["data_source"] == "real"
    assert meta["patch"] == "2026-10"
    assert body.strip() == BODY

    # 2) Chroma 里真有这些 chunk，id 口径 = doc_id#chunk_index
    from app.retrieval.chroma_client import raw_query
    from app.utils.chroma import get_collection

    collection = get_collection()
    stored = collection.get(where={"doc_id": DOC_ID})["ids"]
    assert sorted(stored) == [f"{DOC_ID}#{i}" for i in range(payload["chunks"])]

    # 3) 可被检索：拿自身首块文本查询，相似度应为 1.0 → hero 过滤下必须 top-1
    hits = raw_query(BODY, hero_id="141", patches=["2026-10"], top_k=5)
    assert hits["ids"][0], "带 hero_ids 过滤的查询不应为空"
    assert hits["ids"][0][0] == f"{DOC_ID}#0", (
        "上传的 chunk 未被 hero_ids 过滤召回，说明入库的 metadata 或过滤算子有问题"
    )


async def test_reupload_same_doc_id_replaces_instead_of_appending(
    client, require_chroma, guides_tmp, clean_doc_id
):
    """幂等口径：同 doc_id 二次上传 = 整体替换（chunk 数不涨、id 集合不变）。"""
    require_chroma()

    first = await client.post(
        "/api/docs/upload", data=VALID_FORM, files={"file": ("g.md", BODY, "text/markdown")}
    )
    assert first.status_code == 200
    assert first.json()["replaced"] is False
    count_after_first = first.json()["collection_count"]

    second = await client.post(
        "/api/docs/upload", data=VALID_FORM, files={"file": ("g.md", BODY, "text/markdown")}
    )
    assert second.status_code == 200
    assert second.json()["replaced"] is True, "同一 doc_id 二次上传必须被识别为替换"
    assert second.json()["chunks"] == first.json()["chunks"]
    assert second.json()["collection_count"] == count_after_first, "替换不应让总数漂移"


async def test_upload_without_hero_ids_is_allowed(
    client, require_chroma, guides_tmp
):
    """hero_ids 可空：版本理解 / 通用意识类语料不属于任何单个英雄。

    这条用例抓过一个真实缺陷：chromadb 1.5.9 **拒绝空列表 metadata**
    （`Expected metadata list value for key 'hero_ids' to be non-empty`），
    直接把 `hero_ids: []` 写进去会让合法请求拿到 503。修法见 `corpus_metadata`：空列表省略该键。

    同时断言这类文档**真的能被召回**——`TIER_META` 意图不带 hero 槽位，只按 patch 过滤，
    故「省略 hero_ids」不等于「入库即失联」。规格书 8.1 的「文本-打法/版本」8 条用例正是这条路径。
    """
    require_chroma()

    from app.retrieval.chroma_client import raw_query
    from app.utils.chroma import get_collection

    doc_id = "upload-ut-general"
    form = {**VALID_FORM, "doc_id": doc_id, "hero_ids": "", "topic": "版本理解"}

    def _purge() -> None:
        try:
            get_collection().delete(where={"doc_id": doc_id})
        except Exception:  # noqa: BLE001
            pass

    _purge()
    try:
        r = await client.post(
            "/api/docs/upload", data=form, files={"file": ("g.md", BODY, "text/markdown")}
        )
        assert r.status_code == 200, r.text

        # 落盘侧：front-matter 如实记空列表（重建脚本据此还原「无关联英雄」这一事实）
        meta, _ = parse_guide(guides_tmp / f"{doc_id}.md")
        assert meta["hero_ids"] == [], "空 hero_ids 应如实落成空列表，不得改写成占位值"

        # 入库侧：空列表必须被省略（chromadb 约束），且不能因此失联
        stored = get_collection().get(where={"doc_id": doc_id})
        assert stored["ids"], "空 hero_ids 也必须真的入库"
        assert "hero_ids" not in stored["metadatas"][0], (
            "空 hero_ids 必须省略键（chromadb 拒绝空列表值）；写占位值会污染 $contains 过滤"
        )

        hits = raw_query(BODY, hero_id=None, patches=["2026-10"], top_k=5)
        assert hits["ids"][0][0] == f"{doc_id}#0", (
            "无 hero 过滤（TIER_META 路径）下该文档应可召回，否则「上传成功」等于「查不到」"
        )
    finally:
        _purge()
