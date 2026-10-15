r"""M6 评测执行脚本（规格书 8.1 / 8.2）。

**要产出什么**：把 8.2 的六项指标变成**可重复执行的一条命令**，而不是报告里的一段结论。
输出两类东西：
  1. `docs/milestones/M6-eval-raw.json` —— 每个 turn 的原始记录（意图/实体/证据/答案/耗时/
     生成层留痕），供后续判分脚本与人工抽检复算，**不依赖重新跑模型**；
  2. 屏幕上的汇总表（同时被重定向存成 `M6-eval-output.txt`）。

**为什么走 HTTP `/api/chat/sync` 而不是直接调 `graph.run()`**（5.2 明确「评测脚本依赖它」）：
评测必须打到**对外契约**上 —— 直接调内部函数会绕过 `ChatResponse` 映射与 debug 组装，
「接口返回的字段对不对」这件事就测不到了。这里用 `httpx.ASGITransport` 直连 ASGI app，
不启端口、不依赖网络，但走的是**完整的 HTTP 语义**（路由、序列化、状态码）。

**为什么用内存 checkpointer**：评测要反复建/删会话（每个用例一个 session），落到真实
`data/checkpoints.sqlite` 会留一堆垃圾 thread，且让「本次评测的会话状态」与「用户真实会话」
混在同一个库里。内存库既隔离又完全可复现。`app.agent.graph` 与 `app.api.session` 两处引用
都要 patch —— 只 patch 一处的话，DELETE 端点会去删真实库（M6 集成测试踩过同一个坑）。

**两个评测集分开统计**（需求方 2026-10-15 裁定）：覆盖集 `cases.yaml`（照 8.1 场景构造）
与泛化集 `freeform.yaml`（真实口吻自由问句）分别报准确率，**不得混算成一个数**。

用法：
  .\.venv\Scripts\python.exe scripts/run_eval.py            # 覆盖集 + 泛化集
  .\.venv\Scripts\python.exe scripts/run_eval.py --set coverage
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402
import yaml  # noqa: E402

logging.disable(logging.CRITICAL)   # 节点日志会把评测输出淹掉；要排查时改成 WARNING

from app.agent import graph as graph_mod  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory.checkpointer import open_checkpointer  # noqa: E402

EVAL_DIR = PROJECT_ROOT / "tests" / "eval"
OUT_DIR = PROJECT_ROOT / "docs" / "milestones"
OUT_JSON = OUT_DIR / "M6-eval-raw.json"


def load_cases(name: str) -> list[dict]:
    data = yaml.safe_load((EVAL_DIR / name).read_text(encoding="utf-8"))
    return data["cases"]


def turns_of(case: dict) -> list[dict]:
    """把单轮用例与多轮用例统一成 turn 列表（多轮按顺序在同一 session 内发问）。"""
    if case.get("turns"):
        return list(case["turns"])
    return [{
        "question": case["question"],
        "expected_intent": case.get("expected_intent"),
        "expected_entity_ids": case.get("expected_entity_ids") or [],
        "expected_evidence_contains": case.get("expected_evidence_contains") or [],
        "expect_type": case.get("expect_type"),
    }]


async def ask(client: httpx.AsyncClient, session_id: str, question: str) -> tuple[int, dict, float]:
    t0 = time.perf_counter()
    r = await client.post("/api/chat/sync", json={"session_id": session_id, "question": question})
    dt = time.perf_counter() - t0
    try:
        body = r.json()
    except ValueError:
        body = {"_non_json": r.text[:500]}
    return r.status_code, body, dt


async def run_case(client: httpx.AsyncClient, case: dict, *, set_name: str) -> list[dict]:
    # 每个用例一个独立 session；开跑前先清一次，保证用例之间不串味（跨用例记忆污染）。
    sid = f"m6-{set_name}-{case['id']}"
    await client.delete(f"/api/session/{sid}")

    records: list[dict] = []
    for idx, turn in enumerate(turns_of(case), start=1):
        status, body, dt = await ask(client, sid, turn["question"])
        dbg = body.get("debug") or {}
        gen = dbg.get("generation") or {}
        ent = body.get("entities") or []
        records.append({
            "case_id": case["id"],
            "set": set_name,
            "category": case.get("category"),
            "turn": idx,
            "question": turn["question"],
            "expected_intent": turn.get("expected_intent"),
            "expected_entity_ids": turn.get("expected_entity_ids") or [],
            "expected_evidence_contains": turn.get("expected_evidence_contains") or [],
            "expect_type": turn.get("expect_type"),
            "note": case.get("note"),
            "http_status": status,
            "type": body.get("type"),
            "intent": body.get("intent"),
            "confidence": body.get("confidence"),
            "answer": body.get("answer"),
            "citations": body.get("citations") or [],
            "entity_ids": [e.get("canonical_id") for e in ent if e.get("canonical_id")],
            "entity_names": [e.get("canonical_name") for e in ent],
            "matched_intents": dbg.get("matched_intents") or [],
            "intent_method": dbg.get("intent_method"),
            "coref_resolved": dbg.get("coref_resolved"),
            "resolved_question": dbg.get("resolved_question"),
            "slots": dbg.get("slots") or {},
            "degraded": bool(dbg.get("degraded")),
            "graph_available": dbg.get("graph_available"),
            "top_score": dbg.get("top_score"),
            "evidence_count": dbg.get("evidence_count"),
            "evidence": dbg.get("evidence") or [],
            "generation": gen,
            "guard": gen.get("guard"),
            "guard_degraded": bool(dbg.get("guard_degraded")),
            "error": dbg.get("error"),
            "elapsed_s": round(dt, 3),
        })
    return records


# ---------------------------------------------------------------- 指标

def _pct(hit: int, total: int) -> str:
    return f"{hit}/{total} = {hit / total:.1%}" if total else "0/0 = n/a"


def intent_metrics(recs: list[dict], set_name: str) -> tuple[dict, list[dict]]:
    rows = [r for r in recs if r["set"] == set_name]
    errors = [r for r in rows if r["intent"] != r["expected_intent"]]
    return {"total": len(rows), "correct": len(rows) - len(errors)}, errors


def entity_metrics(recs: list[dict], set_name: str) -> tuple[dict, list[dict]]:
    """实体链接准确率：只在**标注了应有实体**的 turn 上统计。

    为什么把 `expected_entity_ids == []` 的 turn 排除：这类 turn（越界问句、版本问句、
    「我想玩个法师」）本来就**不该**识别出具体英雄，把它们算进分母等于用「真空命中」
    把准确率抬高 —— 那是自欺。分母与口径必须在报告里写清楚。
    """
    rows = [r for r in recs if r["set"] == set_name and r["expected_entity_ids"]]
    errors = [r for r in rows if not set(r["expected_entity_ids"]).issubset(set(r["entity_ids"]))]
    return {"total": len(rows), "correct": len(rows) - len(errors)}, errors


def recall_metrics(recs: list[dict], set_name: str) -> tuple[dict, list[dict]]:
    """Recall@5：关键依据出现在**前 5 条 evidence** 的比例。

    evidence 顺序即融合后的顺序（图谱事实在前、向量按相关度在后），也就是用户展开来源时
    看到的顺序，故「前 5 条」= 真实可见的前 5 条来源。
    """
    rows = [r for r in recs if r["set"] == set_name and r["expected_evidence_contains"]]
    miss = []
    for r in rows:
        top5 = " \n".join((e.get("content") or "") for e in (r["evidence"] or [])[:5])
        if not any(s in top5 for s in r["expected_evidence_contains"]):
            miss.append(r)
    return {"total": len(rows), "correct": len(rows) - len(miss)}, miss


def reject_metrics(recs: list[dict]) -> dict:
    """拒答正确率（双向）：该拒未拒 + 不该拒乱拒（8.2）。两个方向的错误都要报。"""
    should_reject = [r for r in recs if r["expect_type"] == "reject"]
    should_not = [r for r in recs if r["expect_type"] and r["expect_type"] != "reject"]
    missed = [r for r in should_reject if r["type"] != "reject"]
    over = [r for r in should_not if r["type"] == "reject"]
    return {
        "should_reject_total": len(should_reject),
        "missed": missed,
        "should_not_total": len(should_not),
        "over": over,
    }


def composite_ratio(recs: list[dict]) -> dict:
    """复合意图占比（需求方 2026-10-15 第 4 项）：一轮问句命中 ≥2 个意图的比例。

    口径与局限都写进报告：这批问句是**人工构造**的评测集（无线上流量可采样），
    故这是「构造集上的估计」，只能说明「真实用户确实会这样问」，不能当成线上占比。
    """
    multi = [r for r in recs if len(r["matched_intents"]) >= 2]
    return {"total": len(recs), "multi": multi}


def guard_stats(recs: list[dict]) -> dict:
    """guard 触发率（8.2 之外的补充项，需求方 2026-10-15 第 3 项）。

    只在**真正走了 LLM 生成**的 turn 上统计（template 回落路径压根没跑 guard，
    算进分母会把触发率稀释成一个没有意义的数）。
    """
    llm = [r for r in recs if (r["generation"] or {}).get("mode") == "llm"
           and (r["generation"] or {}).get("guard") is not None]
    flagged = [r for r in llm if not (r["guard"] or {}).get("ok")]
    return {"total": len(llm), "flagged": flagged}


def latency_stats(recs: list[dict]) -> dict:
    """/api/chat/sync 的端到端耗时（**不含流式首 token**，那项在 measure_latency.py）。"""
    buckets: dict[str, list[float]] = {}
    for r in recs:
        buckets.setdefault(r["type"] or "?", []).append(r["elapsed_s"])
    out = {}
    for k, v in buckets.items():
        out[k] = {"n": len(v), "mean": round(statistics.mean(v), 2),
                  "p50": round(statistics.median(v), 2), "max": round(max(v), 2)}
    return out


# ---------------------------------------------------------------- 打印

def print_errors(title: str, errors: list[dict]) -> None:
    print(f"\n  --- {title}：错误样例全列（{len(errors)} 条）---")
    if not errors:
        print("    （无）")
        return
    for r in errors:
        print(f"    [{r['case_id']}#{r['turn']}] {r['question']!r}")
        print(f"        期望 intent={r['expected_intent']} / 实际 intent={r['intent']} "
              f"type={r['type']} matched={r['matched_intents']} method={r['intent_method']}")
        print(f"        实体 ids={r['entity_ids']} names={r['entity_names']} "
              f"（期望 {r['expected_entity_ids']}）")
        if r["coref_resolved"]:
            print(f"        指代消解：{r['coref_resolved']}")
        if r["error"]:
            print(f"        error={r['error']}")
        if r["note"]:
            print(f"        标注说明：{r['note']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["coverage", "freeform", "all"], default="all")
    args = ap.parse_args()

    settings.DEBUG = True   # debug 块是评测取中间结果（matched_intents / evidence）的唯一入口

    sets: list[tuple[str, list[dict]]] = []
    if args.set in ("coverage", "all"):
        sets.append(("coverage", load_cases("cases.yaml")))
    if args.set in ("freeform", "all"):
        sets.append(("freeform", load_cases("freeform.yaml")))

    asyncio.run(_main(sets))


async def _main(sets: list[tuple[str, list[dict]]]) -> None:
    all_recs: list[dict] = []
    async with open_checkpointer(":memory:") as cp:
        await graph_mod.reset_graph()

        async def _test_checkpointer():
            return cp

        graph_mod.get_checkpointer = _test_checkpointer
        import app.api.session as session_api
        session_api.get_checkpointer = _test_checkpointer

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as client:
            for set_name, cases in sets:
                print("=" * 78)
                print(f"【评测集 {set_name}】{len(cases)} 条用例")
                print("=" * 78)
                for case in cases:
                    recs = await run_case(client, case, set_name=set_name)
                    all_recs.extend(recs)
                    mark = "OK " if all(r["intent"] == r["expected_intent"] for r in recs) else "ERR"
                    print(f"  {mark} {case['id']:<5} {case.get('question') or case['id']}  "
                          f"-> {[r['intent'] for r in recs]} / {[r['type'] for r in recs]}")

        await graph_mod.reset_graph()

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 78)
    print("【指标汇总】（规格书 8.2；覆盖集与泛化集分开报）")
    print("=" * 78)

    summary: dict = {"total_turns": len(all_recs), "sets": {}}
    for set_name in ("coverage", "freeform"):
        if not any(r["set"] == set_name for r in all_recs):
            continue
        im, ierr = intent_metrics(all_recs, set_name)
        em, eerr = entity_metrics(all_recs, set_name)
        rm, rmiss = recall_metrics(all_recs, set_name)
        print(f"\n[{set_name}]")
        print(f"  意图路由准确率：{_pct(im['correct'], im['total'])}")
        print(f"  实体链接准确率：{_pct(em['correct'], em['total'])}（分母=标注了应有实体的 turn）")
        print(f"  检索 Recall@5 ：{_pct(rm['correct'], rm['total'])}（分母=标注了关键依据的 turn）")
        print_errors(f"{set_name} 意图错误样例", ierr)
        print_errors(f"{set_name} 实体错误样例", eerr)
        print_errors(f"{set_name} Recall@5 未命中", rmiss)
        summary["sets"][set_name] = {
            "intent": {"total": im["total"], "correct": im["correct"]},
            "entity": {"total": em["total"], "correct": em["correct"]},
            "recall5": {"total": rm["total"], "correct": rm["correct"]},
            "intent_errors": [r["case_id"] + "#" + str(r["turn"]) for r in ierr],
            "entity_errors": [r["case_id"] + "#" + str(r["turn"]) for r in eerr],
            "recall5_miss": [r["case_id"] + "#" + str(r["turn"]) for r in rmiss],
        }

    rej = reject_metrics(all_recs)
    print("\n[拒答正确率·双向]")
    print(f"  该拒未拒：{_pct(len(rej['missed']), rej['should_reject_total'])}  "
          f"（标注应拒答的 turn 里没拒的）")
    for r in rej["missed"]:
        print(f"      [{r['case_id']}#{r['turn']}] {r['question']!r} -> type={r['type']}")
    print(f"  不该拒乱拒：{_pct(len(rej['over']), rej['should_not_total'])}  "
          f"（标注不该拒的 turn 里被拒的）")
    for r in rej["over"]:
        print(f"      [{r['case_id']}#{r['turn']}] {r['question']!r} -> intent={r['intent']} "
              f"type={r['type']} note={r['note']}")
    summary["reject"] = {
        "should_reject_total": rej["should_reject_total"], "missed": len(rej["missed"]),
        "should_not_total": rej["should_not_total"], "over": len(rej["over"]),
        "missed_ids": [r["case_id"] + "#" + str(r["turn"]) for r in rej["missed"]],
        "over_ids": [r["case_id"] + "#" + str(r["turn"]) for r in rej["over"]],
    }

    comp = composite_ratio(all_recs)
    print(f"\n[复合意图占比] 命中 ≥2 个意图：{_pct(len(comp['multi']), comp['total'])}")
    for r in comp["multi"]:
        print(f"      [{r['case_id']}#{r['turn']}] {r['question']!r} -> {r['matched_intents']}")
    summary["composite"] = {"total": comp["total"], "multi": len(comp["multi"]),
                            "ids": [r["case_id"] + "#" + str(r["turn"]) for r in comp["multi"]]}

    gs = guard_stats(all_recs)
    print(f"\n[guard 触发率] 走 LLM 生成的 turn 中 guard 拦下：{_pct(len(gs['flagged']), gs['total'])}")
    for r in gs["flagged"]:
        print(f"      [{r['case_id']}#{r['turn']}] {r['question']!r} -> "
              f"{r['guard'].get('reason')}: {r['guard'].get('detail')!r}")
    summary["guard"] = {"llm_turns": gs["total"], "flagged": len(gs["flagged"]),
                        "flagged_ids": [r["case_id"] + "#" + str(r["turn"]) for r in gs["flagged"]]}

    lat = latency_stats(all_recs)
    print("\n[/api/chat/sync 端到端耗时·按响应类型]（秒；流式首 token 见 M6-latency）")
    for k, v in sorted(lat.items()):
        print(f"      {k:<16} n={v['n']:<4} mean={v['mean']:<7} p50={v['p50']:<7} max={v['max']}")
    summary["latency_sync"] = lat

    degraded = [r for r in all_recs if r["degraded"]]
    print(f"\n[降级] 本轮 degraded=True 的 turn：{len(degraded)} 条"
          f"{'（' + ','.join(r['case_id'] for r in degraded[:5]) + '）' if degraded else ''}")
    summary["degraded_turns"] = len(degraded)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"summary": summary, "records": all_recs}, ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    print(f"\n原始记录已写入：{OUT_JSON.relative_to(PROJECT_ROOT)}（{len(all_recs)} 个 turn）")


main()
