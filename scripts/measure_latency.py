r"""M6 首 token 延迟实测 + 句级增量校验可行性评估（规格书 8.2 / 3.4「已知偏差」）。

**规格书要求（8.2 + 3.4）**：
  1. 首 token / 完整回答**分开统计**，必须给**真实数字**；
  2. 评估「句级增量校验」方案，用真实数据支撑「是否切换」的结论。

**为什么必须起真实 uvicorn 而不是用 ASGITransport**：`httpx.ASGITransport` 会把响应体
**整体缓冲**后再返回（它内部 `body_parts.append(...)` 到流结束），首字节时间因此恒等于
完整耗时 —— 用它测首 token 会得到「首 token == 完整回答」的假结论。测流式延迟只能用真端口。

**3.4 已登记的偏差**（本脚本要把它变成数字）：正常回答路径下 prefix 为空，而 guard 要拿
**完整正文**才判得准，所以正文首字节要等「完整生成 + 校验」结束 —— 首 token ≤ 2.5s 在
「正常 answer + llm 路径」下**不可达**；拒答 / 澄清 / template 路径的首 token 是快的。

**三个相位**：
  A. 真实 SSE 端到端：按响应类型分开统计首 token 与完整回答；
  B. 直连模型流：测「首个 reasoning 分片 / 首个正文分片 / 首句完整 / 全文完整」四个时刻 ——
     这是「句级增量校验能省多少」的直接依据（省的是 t_full - t_first_sentence）；
  C. 句级校验覆盖面：拿**真实答案**逐句跑 guard，看「首句即可判」与「跨句才暴露」各占多少。

用法：
  .\.venv\Scripts\python.exe scripts/measure_latency.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

logging.disable(logging.CRITICAL)

from app.config import settings  # noqa: E402
from app.llm.guard import check_answer  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402

PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"
RAW_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-eval-raw.json"

# 覆盖各条检索路径与各响应类型，避免只测「最快的那条路」
QUESTIONS: list[tuple[str, str]] = [
    ("graph", "铠被谁克制"),
    ("graph", "貂蝉克制谁"),
    ("graph", "后羿铭文"),
    ("vector", "貂蝉对线思路"),
    ("vector", "这个版本谁强"),
    ("hybrid", "铠的出装"),
    ("hybrid", "我玩铠怎么打吕布"),
    ("reject", "今天天气怎么样"),
    ("clarify", "我想玩个射手"),
    ("clarify", "怎么打东皇太一"),
]

_SENT_END = re.compile(r"[。！？\n]")


def split_sentences(text: str) -> list[str]:
    """按句末标点切句（句级校验的粒度定义，与 guard 正则「窗口不跨 。；！？」一致）。"""
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if _SENT_END.match(ch):
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out


# ---------------------------------------------------------------- A. 真实 SSE

async def stream_one(client: httpx.AsyncClient, question: str, sid: str) -> dict:
    """打一次 SSE，记录首 token / 首个事件 / done 的时间与终态信息。"""
    payload = {"session_id": sid, "question": question, "stream": True}
    t0 = time.perf_counter()
    first_event = first_token = done_at = None
    events: list[str] = []
    done_data: dict = {}

    async with client.stream("POST", f"{BASE}/api/chat", json=payload, timeout=120.0) as resp:
        if resp.status_code != 200:
            await resp.aread()
            return {"question": question, "http": resp.status_code, "error": "non-200"}
        event = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                now = time.perf_counter() - t0
                if event:
                    events.append(event)
                    if first_event is None:
                        first_event = now
                    if event == "token" and first_token is None:
                        first_token = now
                    if event == "done":
                        done_at = now
                        done_data = json.loads(line[6:])
    return {
        "question": question,
        "http": 200,
        "first_event_s": round(first_event, 3) if first_event is not None else None,
        "first_token_s": round(first_token, 3) if first_token is not None else None,
        "done_s": round(done_at, 3) if done_at is not None else None,
        "type": done_data.get("type"),
        "generation_mode": done_data.get("generation_mode"),
        "fallback": done_data.get("fallback"),
        "intent": done_data.get("intent"),
        "events": events,
    }


async def phase_a() -> list[dict]:
    print("=" * 78)
    print("【相位 A】真实 SSE 端到端延迟（uvicorn 真端口，非 ASGI 缓冲）")
    print("=" * 78)
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, (path, q) in enumerate(QUESTIONS, 1):
            sid = f"m6-lat-{i}"
            await client.delete(f"{BASE}/api/session/{sid}")
            r = await stream_one(client, q, sid)
            r["path"] = path
            rows.append(r)
            print(f"  [{i:02d}] {path:<8} {q:<18} 首事件={r['first_event_s']}  "
                  f"首token={r['first_token_s']}  完整={r['done_s']}  "
                  f"type={r['type']} mode={r['generation_mode']} fallback={r['fallback']}")
            await client.delete(f"{BASE}/api/session/{sid}")

    print("\n  --- 分组统计（秒）---")
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = "template/非生成路径" if r["generation_mode"] != "llm" else "llm 生成路径"
        groups.setdefault(key, []).append(r)
    for key, rs in groups.items():
        ft = [r["first_token_s"] for r in rs if r["first_token_s"] is not None]
        dn = [r["done_s"] for r in rs if r["done_s"] is not None]
        fe = [r["first_event_s"] for r in rs if r["first_event_s"] is not None]
        print(f"  {key}：n={len(rs)}")
        if fe:
            print(f"      首个 SSE 事件  mean={statistics.mean(fe):.2f}  "
                  f"min={min(fe):.2f}  max={max(fe):.2f}")
        if ft:
            print(f"      首 token       mean={statistics.mean(ft):.2f}  "
                  f"min={min(ft):.2f}  max={max(ft):.2f}")
        if dn:
            print(f"      完整回答       mean={statistics.mean(dn):.2f}  "
                  f"min={min(dn):.2f}  max={max(dn):.2f}")
    return rows


# ---------------------------------------------------------------- B. 直连模型流

def phase_b() -> list[dict]:
    """直连模型流，测四个时刻。用**评测跑出来的真实 evidence**构造 prompt，避免另造资料。"""
    print("\n" + "=" * 78)
    print("【相位 B】直连模型流：首个正文分片 / 首句完整 / 全文完整（句级校验能省多少）")
    print("=" * 78)
    if not RAW_JSON.exists():
        print(f"  缺少 {RAW_JSON.name}（先跑 scripts/run_eval.py）；本相位跳过。")
        return []

    raw = json.loads(RAW_JSON.read_text(encoding="utf-8"))
    picks: list[dict] = []
    for r in raw["records"]:
        if (r["generation"] or {}).get("mode") == "llm" and r["type"] in ("answer", "low_confidence") \
                and len(picks) < 3 and r["evidence"]:
            picks.append(r)
    if not picks:
        print("  评测记录里没有 llm 生成路径的样例；本相位跳过。")
        return []

    rows: list[dict] = []
    for r in picks:
        ev = [Evidence(**{k: e.get(k) for k in
                          ("kind", "content", "relation", "score", "source", "patch", "hero_ids")
                          if k in e}) for e in r["evidence"]]
        msgs = build_messages(r["question"], ev)
        rows.append(_stream_timed(r["question"], msgs))

    for r in rows:
        print(f"  {r['question']!r}")
        print(f"      首个 reasoning 分片 = {r['first_reasoning_s']}s")
        print(f"      首个正文分片        = {r['first_content_s']}s")
        print(f"      首句完整            = {r['first_sentence_s']}s  （{r['first_sentence']!r}）")
        print(f"      全文完整            = {r['full_s']}s")
        if r["first_sentence_s"] and r["full_s"]:
            print(f"      >>> 句级校验可提前推送正文：{r['full_s'] - r['first_sentence_s']:.2f}s "
                  f"（相对现方案 {r['full_s']:.2f}s 节省 "
                  f"{(r['full_s'] - r['first_sentence_s']) / r['full_s']:.0%}）")
    return rows


def _stream_timed(question: str, messages: list[dict]) -> dict:
    """同 `CloudChatClient.stream_chat` 的协议，但**逐分片打时间戳**（客户端本身不暴露时序）。"""
    payload = {
        "model": settings.CLOUD_CHAT_MODEL,
        "messages": messages,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {"Authorization": f"Bearer {settings.CLOUD_API_KEY}",
               "Content-Type": "application/json"}
    t0 = time.perf_counter()
    content = ""
    first_reasoning = first_content = first_sentence = full = None
    finish = None
    with httpx.stream("POST", f"{settings.CLOUD_BASE_URL.rstrip('/')}/chat/completions",
                      json=payload, headers=headers, timeout=settings.LLM_TIMEOUT) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                full = time.perf_counter() - t0
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            choice = (obj.get("choices") or [{}])[0]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content") and first_reasoning is None:
                first_reasoning = time.perf_counter() - t0
            if delta.get("content"):
                if first_content is None:
                    first_content = time.perf_counter() - t0
                content += delta["content"]
                if first_sentence is None and _SENT_END.search(content):
                    first_sentence = time.perf_counter() - t0
    if full is None:
        full = time.perf_counter() - t0
    return {
        "question": question,
        "first_reasoning_s": round(first_reasoning, 3) if first_reasoning else None,
        "first_content_s": round(first_content, 3) if first_content else None,
        "first_sentence_s": round(first_sentence, 3) if first_sentence else None,
        "first_sentence": (split_sentences(content)[0][:40] if content else None),
        "full_s": round(full, 3),
        "finish_reason": finish,
        "content": content,
    }


# ---------------------------------------------------------------- C. 句级校验覆盖面

def phase_c(rows: list[dict]) -> dict:
    """用**真实答案**（相位 B 的 3 条 + 评测记录里的 LLM 答案）逐句跑 guard。

    要回答的问题是：「句级增量校验」相比现行「全文校验」会漏掉什么？
    判据：某答案若**全文校验判越界**、但**任何句级前缀都判不出越界**，
    说明该越界依赖跨句上下文 —— 句级方案会漏检。
    """
    print("\n" + "=" * 78)
    print("【相位 C】句级增量校验覆盖面（拿真实答案逐句跑 guard）")
    print("=" * 78)

    corpus: list[dict] = []
    for r in rows:
        if r["content"]:
            corpus.append({"question": r["question"], "answer": r["content"], "source": "相位B"})
    if RAW_JSON.exists():
        raw = json.loads(RAW_JSON.read_text(encoding="utf-8"))
        for rec in raw["records"]:
            gen = rec["generation"] or {}
            if gen.get("mode") == "llm" and (rec["answer"] or "").strip():
                corpus.append({"question": rec["question"], "answer": rec["answer"],
                               "source": f"{rec['case_id']}#{rec['turn']}",
                               "evidence": rec["evidence"]})

    n_full_flag = n_sent_flag = n_full_only = 0
    details = []
    for item in corpus:
        ev = []
        for e in item.get("evidence") or []:
            ev.append(Evidence(**{k: e.get(k) for k in
                                  ("kind", "content", "relation", "score", "source", "patch", "hero_ids")
                                  if k in e}))
        q = item["question"]
        full = check_answer(item["answer"], ev, q)
        # 句级：逐句累积成前缀，任一前缀被判越界即「句级可判」
        prefixes = []
        acc = ""
        for s in split_sentences(item["answer"]):
            acc += s
            prefixes.append(acc)
        sent_at = None
        for i, p in enumerate(prefixes, 1):
            if not check_answer(p, ev, q).ok:
                sent_at = i
                break
        if not full.ok:
            n_full_flag += 1
            if sent_at is None:
                n_full_only += 1
        if sent_at is not None:
            n_sent_flag += 1
        details.append({"source": item["source"], "question": q,
                        "full_ok": full.ok, "full_reason": full.reason,
                        "sent_flag_at": sent_at, "sentences": len(prefixes),
                        "answer": item["answer"][:120]})

    print(f"  样本数（真实 LLM 答案）：{len(corpus)}")
    print(f"  全文校验判越界：{n_full_flag} 条")
    print(f"  句级前缀能判出越界：{n_sent_flag} 条")
    print(f"  **全文判越界但句级判不出（跨句依赖，句级会漏检）**：{n_full_only} 条")
    print("  --- 明细（仅列被任一方式判越界的样本）---")
    for d in details:
        if not d["full_ok"] or d["sent_flag_at"]:
            print(f"    {d['source']} 句数={d['sentences']}  全文ok={d['full_ok']}"
                  f"({d['full_reason']})  句级命中于第 {d['sent_flag_at']} 句  {d['answer']!r}")
    return {"corpus": len(corpus), "full_flag": n_full_flag,
            "sent_flag": n_sent_flag, "full_only": n_full_only}


# ---------------------------------------------------------------- 入口

def start_server() -> subprocess.Popen:
    # 子进程日志落到系统临时目录：启动失败时可事后排查（原 DEVNULL 导致无从定位）
    log_path = Path(tempfile.gettempdir()) / "m6-latency-uvicorn.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "uvicorn",
         "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(PROJECT_ROOT), stdout=log, stderr=log,
    )
    # /api/health 首次调用要连 Neo4j + 打开 Chroma（冷启动可达数秒），
    # 原先 2s 的探活超时会把「服务其实已就绪」反复误判成未就绪；放宽到 15s，总上限 120s。
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/api/health", timeout=15.0).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"uvicorn 未在 120s 内就绪；子进程日志见 {log_path}")


def main() -> None:
    settings.DEBUG = True
    proc = start_server()
    try:
        rows_a = asyncio.run(phase_a())
        rows_b = phase_b()
        stats_c = phase_c(rows_b)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n" + "=" * 78)
    print("【结论数据】")
    print("=" * 78)
    llm = [r for r in rows_a if r["generation_mode"] == "llm" and r["first_token_s"]]
    tpl = [r for r in rows_a if r["generation_mode"] != "llm" and r["first_token_s"]]
    if llm:
        print(f"  llm 生成路径 首 token：mean={statistics.mean([r['first_token_s'] for r in llm]):.2f}s "
              f"（目标 ≤2.5s）-> 见 3.4 已登记偏差")
    if tpl:
        print(f"  template/非生成路径 首 token："
              f"mean={statistics.mean([r['first_token_s'] for r in tpl]):.2f}s")
    if rows_b:
        saves = [r["full_s"] - r["first_sentence_s"] for r in rows_b
                 if r["full_s"] and r["first_sentence_s"]]
        if saves:
            print(f"  句级校验可提前推送正文：平均提前 {statistics.mean(saves):.2f}s")
    print(f"  句级校验漏检（跨句依赖）：{stats_c['full_only']}/{stats_c['full_flag']} 条全文判越界的样本")

    out = PROJECT_ROOT / "docs" / "milestones" / "M6-latency-raw.json"
    out.write_text(json.dumps({"phase_a": rows_a, "phase_b": rows_b, "phase_c": stats_c},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始记录已写入：{out.relative_to(PROJECT_ROOT)}")


main()
