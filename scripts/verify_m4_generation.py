r"""M4 验收证据脚本：生成层的真实云端运行输出（可复跑）。

与 M2 的 `verify_data_layer.py`、M3 的 `verify_api_smoke.py` 同属「复跑校验」类脚本 ——
把报告里的结论变成可重复执行的命令，而不是只能靠人工复述。

**本脚本会真实调用云端**（需 `.env` 内 `CLOUD_API_KEY` 可用），共约 6 次调用，成本极低。

六段证据（对应 M4 验收项 + 需求方 2026-10-15 的三条实测约束）：

  A 环境与依赖状态      —— `/api/health` 三项真实状态；意图路径**完全离线**（不触任何
                           外部模型服务）由 `tests/unit/test_llm_offline_resilience.py` 固化
  B 真实云端生成（非流式）—— `reasoning_content` 与正文**隔离**、`finish_reason` /
                           `completion_tokens`（含思考）口径
  C 真实云端流式         —— reasoning 分片触发一次「正在思考」，**不混入正文**
  D 越界归纳拦截         —— 需求方实测原案：prompt 挡不住 -> guard 拦下 -> 回落确定性组装
  E 空答案 fail-fast     —— `max_tokens=200` 复现「HTTP 200 + finish_reason=length + content 空」-> 抛错
  F 端到端 `/api/chat/sync`（`GENERATION_MODE=llm`）—— 真实回答 + `debug.generation_info`

用法（Neo4j 在线供 F 段使用）：
  python scripts/verify_m4_generation.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm.client import CloudChatClient, LLMGenerationError, get_cloud_client  # noqa: E402
from app.llm.guard import check_answer  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402

GRAPH = PROJECT_ROOT / "data" / "graph"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _kai_counter_case() -> tuple[str, list[Evidence]]:
    """「铠被谁克制」：资料直接取自本地快照的 COUNTERS 入边（含官方 reason）。"""
    rels = json.loads((GRAPH / "relations.json").read_text(encoding="utf-8"))
    counters = [r for r in rels if r["type"] == "COUNTERS" and r["to_name"] == "铠"][:4]
    ev = [
        Evidence(
            kind="graph",
            content=f"{r['from_name']} 克制 铠：{r['reason']}",
            source="official", relation="COUNTERS", patch="2026-10",
        )
        for r in counters
    ]
    return "铠被谁克制？", ev


def _inscription_case() -> tuple[str, list[Evidence]]:
    """「铠的铭文」：重问题（思考吃 token 多），用于复现 max_tokens 截断。"""
    heroes = {h["name"]: h for h in json.loads((GRAPH / "heroes.json").read_text(encoding="utf-8"))}
    ins = {i["id"]: i for i in json.loads((GRAPH / "inscriptions.json").read_text(encoding="utf-8"))}
    kai = heroes["铠"]
    ev = [
        Evidence(
            kind="vector",
            content=f"{ins[i]['color']}：{ins[i]['name']}（{ins[i]['des']}）",
            source="guide", patch="2026-10",
        )
        for i in kai["ming_sets"][0]
    ]
    return "铠的铭文怎么搭配？", ev


def _leak_case() -> tuple[str, list[Evidence]]:
    """需求方实测原案：资料把**解释**写在了 reason 里，模型会把解释当**类别**来答。"""
    ev = [
        Evidence(
            kind="graph",
            content="妲己 克制 后羿：后羿怕高爆发法师",
            source="official", relation="COUNTERS", patch="2026-10",
        )
    ]
    return "后羿怕什么？", ev


# ---------------------------------------------------------------- A 环境

def section_a() -> None:
    _rule("【A】环境与依赖状态（/api/health）")
    from app.api.health import _check_chroma, _check_llm, _check_neo4j

    print(f"CLOUD_CHAT_MODEL={settings.CLOUD_CHAT_MODEL}  "
          f"LLM_MAX_TOKENS={settings.LLM_MAX_TOKENS}  GENERATION_MODE={settings.GENERATION_MODE}")
    for name, fn in (("neo4j", _check_neo4j), ("chroma", _check_chroma), ("llm", _check_llm)):
        st = fn()
        print(f"  {name:<8} ok={st['ok']}  {st['detail']}")
    print("  注：意图识别走确定性规则路径，**不触任何外部模型服务**；该离线韧性由"
          " tests/unit/test_llm_offline_resilience.py 固化（health 探测只回状态不抛错）。")


# ---------------------------------------------------------------- B 非流式

def section_b(client: CloudChatClient) -> None:
    _rule("【B】真实云端生成（非流式）：reasoning 与正文隔离")
    question, ev = _kai_counter_case()
    result = client.chat(build_messages(question, ev))

    print(f"问题：{question}")
    print(f"资料 {len(ev)} 条（前 2 条）：")
    for e in ev[:2]:
        print(f"  - {e.content}")
    print(f"\nmodel={result.model}  finish_reason={result.finish_reason}")
    print(f"completion_tokens={result.completion_tokens}（含思考）  "
          f"reasoning_tokens={result.reasoning_tokens}  reasoning 字符={len(result.reasoning)}")
    print(f"is_success={result.is_success}（判定：content 非空 AND finish_reason != 'length'）")
    print(f"\n正文 content（{len(result.content)} 字）：\n{result.content}")
    leaked = result.reasoning and result.reasoning in result.content
    print(f"\n[检查] 思考是否混入正文：{'是（异常）' if leaked else '否（正确隔离）'}")


# ---------------------------------------------------------------- C 流式

def section_c(client: CloudChatClient) -> None:
    _rule("【C】真实云端流式：reasoning 分片 -> 「正在思考」，不混入正文")
    question, ev = _kai_counter_case()
    ticks = {"n": 0}

    def _on_reasoning() -> None:
        ticks["n"] += 1
        print("  [thinking] 正在思考")

    result = client.stream_chat(build_messages(question, ev), on_reasoning=_on_reasoning)

    print(f"model={result.model}  finish_reason={result.finish_reason}")
    print(f"completion_tokens={result.completion_tokens}  reasoning_tokens={result.reasoning_tokens}")
    print(f"thinking 事件触发次数={ticks['n']}（首个 reasoning 分片触发一次）")
    print(f"思考字符数={len(result.reasoning)}  正文字符数={len(result.content)}")
    print(f"\n正文 content：\n{result.content}")
    leaked = result.reasoning and result.reasoning in result.content
    print(f"\n[检查] 思考是否混入正文：{'是（异常）' if leaked else '否（正确隔离）'}")


# ---------------------------------------------------------------- D 越界拦截

def section_d(client: CloudChatClient) -> None:
    _rule("【D】越界归纳拦截（需求方实测原案：把资料里的解释当类别）")
    question, ev = _leak_case()
    messages = build_messages(question, ev)

    raw = client.chat(messages)
    print(f"问题：{question}")
    print(f"资料：{ev[0].content}")
    print(f"\n模型原始正文：{raw.content!r}")

    verdict = check_answer(raw.content, ev, question)
    print(f"\n[guard] ok={verdict.ok}  reason={verdict.reason}  detail={verdict.detail!r}")

    # 完整节点路径：guard 不通过 -> 回落确定性证据组装
    from app.agent.nodes.generate import generate_node

    settings.GENERATION_MODE = "llm"
    out = generate_node({
        "question": question, "resolved_question": question,
        "evidence": ev, "response_type": "answer", "intent": "COUNTER_BY",
        "matched_intents": ["COUNTER_BY"],
    })
    info = out["generation_info"]
    print(f"\n[generate 节点] mode={info['mode']}  fallback={info['fallback']}  "
          f"guard={info.get('guard')}")
    print(f"交付给用户的答案（确定性组装）：\n{out['answer']}")
    print(f"\n[检查] 越界原文是否被交付："
          f"{'是（异常）' if raw.content.strip() in out['answer'] else '否（已回落）'}")


# ---------------------------------------------------------------- E 空答案

def section_e() -> None:
    _rule("【E】空答案 fail-fast：max_tokens=200 复现（HTTP 200 + finish_reason=length + content 空）")
    question, ev = _inscription_case()
    tiny = CloudChatClient(
        base_url=settings.CLOUD_BASE_URL, api_key=settings.CLOUD_API_KEY,
        model=settings.CLOUD_CHAT_MODEL, timeout=settings.LLM_TIMEOUT, max_tokens=200,
    )
    print(f"问题：{question}（重问题：思考吃 token 多）")
    print(f"max_tokens=200（远小于 LLM_MAX_TOKENS={settings.LLM_MAX_TOKENS}）")
    try:
        r = tiny.chat(build_messages(question, ev))
        print(f"未抛错：finish_reason={r.finish_reason} content_len={len(r.content)} "
              f"is_success={r.is_success}（本次未触发截断）")
    except LLMGenerationError as e:
        print(f"LLMGenerationError: {e}")
        print("[检查] 空答案被拦下（未当正常回答往下走）：是（正确）")


# ---------------------------------------------------------------- F 端到端

async def section_f() -> None:
    _rule("【F】端到端 /api/chat/sync（GENERATION_MODE=llm，真实云端）")
    from app.agent import graph as graph_mod
    from app.main import app
    from app.memory.checkpointer import open_checkpointer

    settings.GENERATION_MODE = "llm"
    settings.DEBUG = True

    async with open_checkpointer(":memory:") as cp:
        await graph_mod.reset_graph()

        async def _test_checkpointer():
            return cp

        graph_mod.get_checkpointer = _test_checkpointer

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for q, sid in (("铠被谁克制", "m4-e2e-1"), ("铠的出装和铭文", "m4-e2e-2")):
                r = await client.post("/api/chat/sync", json={"session_id": sid, "question": q})
                b = r.json()
                info = (b.get("debug") or {}).get("generation") or {}
                print(f"\nPOST /api/chat/sync  question={q!r}")
                print(f"  HTTP {r.status_code}  type={b['type']}  intent={b['intent']}  "
                      f"confidence={b['confidence']}")
                print(f"  citations={len(b['citations'])}  "
                      f"matched_intents={b['debug']['matched_intents']}")
                print(f"  generation_info: mode={info.get('mode')} fallback={info.get('fallback')} "
                      f"model={info.get('model')} finish={info.get('finish_reason')} "
                      f"completion_tokens={info.get('completion_tokens')} "
                      f"reasoning_chars={info.get('reasoning_chars')} guard={info.get('guard')}")
                print(f"  answer={b['answer'][:200]!r}")

        await graph_mod.reset_graph()


def main() -> None:
    client = get_cloud_client()
    if client is None:
        print("云端 LLM 未配置（缺 CLOUD_BASE_URL / CLOUD_API_KEY / CLOUD_CHAT_MODEL），无法产出 M4 证据。")
        return

    print("=" * 78)
    print("M4 生成层验收证据（真实云端调用）")
    print("=" * 78)

    section_a()
    section_b(client)
    section_c(client)
    section_d(client)
    section_e()
    asyncio.run(section_f())


main()
