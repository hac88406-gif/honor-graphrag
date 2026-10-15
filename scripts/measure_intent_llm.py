r"""M6 裁决用：LLM 意图路径（`route_llm`）到底值不值得留。

**为什么必须做这个测量**：`app/retrieval/intent.py` 里有两条路径，但**生产路径只走规则**
（`app/agent/nodes/intent.py` 直接调 `route_rules`，从不 `use_llm=True`）——
于是 `route_llm` 是「写了但没接、也没测过」的代码。项目规矩是**不留无法验证的悬空实现**，
故在 M6 用同一批问句把两条路径放在一起比：准确率、差异样例、单次延迟。

**对比口径**：
  - 输入完全相同的问句（同一条用例文本），只换路由器，故差异只来自路由策略本身；
  - **排除多轮追问用例**：它们的 `expected_intent` 依赖指代消解（`app/agent/coref.py`），
    而两条路径在这一层都拿不到上一轮状态，比出来的差异是噪声而非路由能力差异；
  - Ollama 不可达时 **fail-fast**（报错退出），不得静默跳过 —— 静默跳过会让人误以为「测过」。

用法：
  .\.venv\Scripts\python.exe scripts/measure_intent_llm.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")

import httpx  # noqa: E402
import yaml  # noqa: E402

from app.config import settings  # noqa: E402
from app.retrieval.intent import route  # noqa: E402

EVAL_DIR = PROJECT_ROOT / "tests" / "eval"
OUT_TXT = PROJECT_ROOT / "docs" / "milestones" / "M6-intent-llm-output.txt"
OUT_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-intent-llm-raw.json"

_lines: list[str] = []


def emit(s: str = "") -> None:
    print(s)
    _lines.append(s)


def probe_ollama() -> None:
    """Ollama 不可达即 fail-fast：本次测量无从进行，必须报错而不是跳过。"""
    try:
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Ollama 不可达（{settings.OLLAMA_BASE_URL}）：{e}\n"
                         "本测量需要本地意图模型，服务未起时不得静默跳过。")


def load_single_turn_cases(name: str) -> list[dict]:
    data = yaml.safe_load((EVAL_DIR / name).read_text(encoding="utf-8"))
    out = []
    for c in data["cases"]:
        if c.get("turns"):        # 多轮追问：期望值依赖指代消解，不参与本对比
            continue
        if not c.get("expected_intent"):
            continue
        out.append({"case_id": c["id"], "set": name.split(".")[0], "category": c.get("category"),
                    "question": c["question"], "expected": c["expected_intent"]})
    return out


def main() -> None:
    probe_ollama()
    cases = load_single_turn_cases("cases.yaml") + load_single_turn_cases("freeform.yaml")

    emit("=" * 78)
    emit(f"M6 LLM 意图路径（route_llm）对比 · model={settings.INTENT_MODEL}")
    emit("=" * 78)
    emit(f"问句 {len(cases)} 条（已排除多轮追问：其期望值依赖指代消解，两条路径都拿不到上下文）")
    emit("")

    rows = []
    for c in cases:
        t0 = time.perf_counter()
        rule = route(c["question"], use_llm=False)
        dt_rule = time.perf_counter() - t0
        t0 = time.perf_counter()
        llm = route(c["question"], use_llm=True)
        dt_llm = time.perf_counter() - t0
        rows.append({**c, "rule": rule.intent, "rule_method": rule.method, "rule_s": dt_rule,
                     "llm": llm.intent, "llm_method": llm.method, "llm_s": dt_llm,
                     "rule_ok": rule.intent == c["expected"], "llm_ok": llm.intent == c["expected"]})

    def rate(sel: str, key: str) -> tuple[int, int]:
        sub = [r for r in rows if r["set"] == sel] if sel != "all" else rows
        return sum(r[key] for r in sub), len(sub)

    for sel in ("all", "cases", "freeform"):
        label = {"all": "合计", "cases": "覆盖集", "freeform": "泛化集"}[sel]
        ro, n = rate(sel, "rule_ok")
        lo, _ = rate(sel, "llm_ok")
        emit(f"  {label}：规则 {ro}/{n} = {ro/n:.1%}     LLM {lo}/{n} = {lo/n:.1%}")

    ok_rule = [r["rule_s"] for r in rows]
    ok_llm = [r["llm_s"] for r in rows]
    emit("")
    emit(f"  单次耗时：规则 mean={sum(ok_rule)/len(ok_rule)*1000:.1f}ms    "
         f"LLM mean={sum(ok_llm)/len(ok_llm):.2f}s "
         f"(min={min(ok_llm):.2f}s max={max(ok_llm):.2f}s)")
    emit(f"  LLM 路径实际生效（method=llm）条数：{sum(1 for r in rows if r['llm_method'] == 'llm')}/{len(rows)}")

    emit("")
    emit("--- 两条路径结论不同的用例（逐条列全） ---")
    diff = [r for r in rows if r["rule"] != r["llm"]]
    if not diff:
        emit("  （无：两条路径在所有问句上结论一致）")
    for r in diff:
        mark = ("LLM 更准" if r["llm_ok"] and not r["rule_ok"] else
                "规则更准" if r["rule_ok"] and not r["llm_ok"] else "都错/都另有出入")
        emit(f"  [{r['case_id']}] {r['question']!r}")
        emit(f"      期望={r['expected']}  规则={r['rule']}  LLM={r['llm']}  -> {mark}")

    emit("")
    emit("--- 规则路径判错的用例（LLM 是否能救回） ---")
    for r in rows:
        if not r["rule_ok"]:
            emit(f"  [{r['case_id']}] {r['question']!r} 期望={r['expected']} "
                 f"规则={r['rule']} LLM={r['llm']} "
                 f"-> {'LLM 救回' if r['llm_ok'] else 'LLM 也错'}")

    OUT_TXT.write_text("\n".join(_lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"model": settings.INTENT_MODEL, "rows": rows},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    emit("")
    emit(f"原始记录已写入：{OUT_JSON.relative_to(PROJECT_ROOT)}")


main()
