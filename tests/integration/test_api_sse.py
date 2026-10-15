"""M5 集成测试 —— `POST /api/chat` 的 SSE 事件协议（规格书 5.2 / 5.3）。

M5 验收原文：「SSE 流式逐字显示；节点进度可见；来源卡片可展开；拒答与澄清有差异化样式」。
前三条都依赖**后端事件流**真的按 5.3 吐出来，故这里对事件序列做编排级断言：

  - 正常回答：node_start（节点进度）-> evidence（来源卡片的数据源）-> token（正文）-> citation -> done；
  - 拒答    ：`done.type == "reject"`，**无 evidence、citations 为空**（差异化渲染的依据）；
  - 澄清    ：`done.type == "clarify"`，**`clarify_options` 非空**（否则前端没法把候选渲染成可点选项）。

**为什么不用真实检索**：`retrieval_stubbed` 把两路检索换成可控输入 —— 这里要测的是
「SSE 帧格式 + 事件顺序 + type 分流」，真实 Neo4j/Chroma 只会引入数据依赖与不确定性。
故本文件在开发/验收两模式下都能跑（不挂服务门禁）。

**为什么断言的是帧文本而不是用 sse-starlette 的解析器**：后端本来就没引该依赖
（见 DECISIONS「M5：SSE 用原生 StreamingResponse」），若测试反向依赖它，
就变成「测试逼着实现引包」—— 直接用最小解析器校验帧格式更贴合真实契约。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.agent import graph as graph_mod
from app.schemas.chat import Evidence

GRAPH_EV = Evidence(
    kind="graph", content="兰陵王 克制 铠：兰陵王隐身突进，铠难反制", source="official",
    relation="COUNTERS", patch="2026-10", hero_ids=["153", "166"],
)


@pytest.fixture
async def client(checkpointer, monkeypatch):
    """ASGI 直连客户端，与测试同处**一个事件循环**（同 test_graph_degrade 的理由）。

    把 `get_graph()` 依赖的 checkpointer 指向测试用的内存库，
    因此走的仍是**真实的** `stream_events()` 路径，只是不落真实会话文件。
    """
    await graph_mod.reset_graph()

    async def _test_checkpointer():
        return checkpointer

    monkeypatch.setattr(graph_mod, "get_checkpointer", _test_checkpointer)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await graph_mod.reset_graph()


@pytest.fixture
def retrieval_stubbed(monkeypatch):
    """把两路检索换成可控输入（同 test_m4_acceptance 的做法）。"""
    def _install(*, graph: list[Evidence], vector: list[Evidence]):
        monkeypatch.setattr("app.agent.nodes.graph_query.query_evidence",
                            lambda template, **kw: list(graph))
        monkeypatch.setattr("app.agent.nodes.vector_search.hybrid_search",
                            lambda question, **kw: list(vector))
    return _install


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """最小 SSE 解析器：`event: X` + `data: <json>`，空行分帧（5.3）。

    只解析本后端实际吐出的形态，不追求兼容 SSE 全量规范 —— 测试与实现共用一份最小契约。
    """
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: "):].strip()
        elif line.startswith("data: ") and name is not None:
            events.append((name, json.loads(line[len("data: "):])))
    return events


async def stream_chat(client, session_id: str, question: str) -> tuple[httpx.Response, list[tuple[str, dict]]]:
    async with client.stream(
        "POST", "/api/chat", json={"session_id": session_id, "question": question, "stream": True}
    ) as resp:
        body = "".join([chunk async for chunk in resp.aiter_text()])
    return resp, parse_sse(body)


# ---------------------------------------------------------------- 正常回答路径


async def test_answer_path_emits_full_event_sequence(client, retrieval_stubbed):
    """正常回答：节点进度 / 来源 / 正文 / citation / done 一个都不能少。"""
    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    resp, events = await stream_chat(client, "sse-answer", "铠被谁克制")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    names = [n for n, _ in events]
    assert names[-1] == "done", "done 必须是最后一帧"
    assert "node_start" in names, "M5 验收：节点进度可见"
    assert "evidence" in names, "来源卡片的数据源（逐条推送）"
    assert "token" in names, "M5 验收：流式逐字显示"
    assert "citation" in names

    # 节点进度：实体链接与意图路由是每轮必跑的起点
    nodes = [d["node"] for n, d in events if n == "node_start"]
    assert nodes[:2] == ["entity_linking", "intent_routing"]

    # 来源：evidence 帧的载荷就是 5.1 的 Evidence（前端据此展开来源卡片）
    ev = next(d["evidence"] for n, d in events if n == "evidence")
    assert ev["content"] == GRAPH_EV.content
    assert ev["patch"] == "2026-10"

    # citation：index 与 evidence 顺序一一对应（前端按 index 配对展开）
    cits = next(d["citations"] for n, d in events if n == "citation")
    assert [c["index"] for c in cits] == [1]
    assert cits[0]["label"] == GRAPH_EV.content

    done = events[-1][1]
    assert done["type"] in {"answer", "low_confidence"}
    assert done["confidence"] > 0
    assert done["clarify_options"] == []


async def test_token_frames_concatenate_to_final_answer(client, retrieval_stubbed):
    """逐段 token 拼起来必须等于最终答案（5.3「逐字显示」不能与 done 后取到的不一致）。"""
    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    _, events = await stream_chat(client, "sse-token", "铠被谁克制")

    streamed = "".join(d["text"] for n, d in events if n == "token")
    assert GRAPH_EV.content in streamed, "确定性组装必须把 evidence 原文推给前端"


async def test_token_frames_are_incremental_not_one_shot(client, retrieval_stubbed):
    """M5 验收「SSE 流式逐字显示」：正文必须**分多帧**推，不能一帧整段。

    一帧整段的话，前端拿到的是「一次性显示」，协议上也不再是 5.3 那种
    `event: token data: {"text": "铠"}` 的逐段形态 —— 看起来像流式，实际不是。
    """
    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    _, events = await stream_chat(client, "sse-chunk", "铠被谁克制")

    texts = [d["text"] for n, d in events if n == "token"]
    assert len(texts) > 1, f"正文必须分多帧推，实际只有 {len(texts)} 帧"
    assert max(len(t) for t in texts) <= 8, "单帧不得超过分块粒度（8 字）"
    assert GRAPH_EV.content in "".join(texts), "分块不得丢字或改字"


async def test_citation_is_pushed_before_body_tokens(client, retrieval_stubbed):
    """规格书 v1.6 §3.4：依据在检索阶段就已确定，不必等生成 —— citation 必须**先于正文**到达。

    否则「先看到查到了哪些依据」的感知改善落不了地：用户仍要等完整生成（llm 路径 3~6s）之后
    才看到来源卡片。顺带钉住「每条路径**恰好一次** citation」，防止提前推之后末尾又重复推一份。
    """
    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    _, events = await stream_chat(client, "sse-early-cit", "铠被谁克制")

    names = [n for n, _ in events]
    assert names.index("citation") < names.index("token"), "citation 必须先于正文 token 到达"
    assert names.count("citation") == 1, "citation 只推一次（不得提前推后又在末尾重复）"
    # 提前推的 citation 仍是 5.1 的 1-based 序号，与 evidence 顺序一致（前端据此配对展开）
    cits = next(d["citations"] for n, d in events if n == "citation")
    assert [c["index"] for c in cits] == [1]


# ---------------------------------------------------------------- 拒答路径


async def test_reject_path_has_no_sources_and_distinct_type(client):
    """越界问句 -> 拒答：无来源、无 citation，`type=reject`（差异化渲染的依据）。"""
    resp, events = await stream_chat(client, "sse-reject", "今天天气怎么样")

    assert resp.status_code == 200
    names = [n for n, _ in events]
    assert "evidence" not in names
    assert events[-1][0] == "done"
    assert events[-1][1]["type"] == "reject"

    cits = next(d["citations"] for n, d in events if n == "citation")
    assert cits == [], "拒答不得给来源卡片"

    answer = "".join(d["text"] for n, d in events if n == "token")
    assert answer, "拒答必须给出可替代的提问方向，不能空"


# ---------------------------------------------------------------- 澄清路径


async def test_clarify_path_carries_options(client):
    """实体未识别 -> 澄清：`type=clarify` 且 `clarify_options` 非空（前端渲染成可点选项）。"""
    resp, events = await stream_chat(client, "sse-clarify", "赛博坦这个英雄怎么样")

    assert resp.status_code == 200
    done = events[-1][1]
    assert done["type"] == "clarify"
    assert done["clarify_options"], "澄清必须给候选，否则前端无法差异化渲染（4.3）"
    assert done["type"] != "reject", "9.2-5：实体未识别不得走拒答"


# ---------------------------------------------------------------- 非流式分支


async def test_stream_false_returns_plain_json(client):
    """`stream=False` 不是被静默忽略：按 5.1 返回完整 ChatResponse（与 /chat/sync 同构）。"""
    resp = await client.post(
        "/api/chat", json={"session_id": "sse-json", "question": "今天天气怎么样", "stream": False}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["type"] == "reject"
    assert body["session_id"] == "sse-json"
