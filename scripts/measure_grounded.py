r"""M6 答案有据率（规格书 8.2）—— 对**全评测集**的答案做「资料忠实度」判分。

**为什么单独一个脚本**：`run_eval.py` 只算确定性指标（意图 / 实体 / 召回 / 拒答），
「答案有据率」必须靠 LLM 判官才能判（它要识别「换个说法但仍是越界」的形态），
而判官调用有成本、有噪声，故独立成一个可复跑、可留痕的步骤，而不是塞进主评测循环。

**判据来源**：复用 `scripts/eval_judge.py` —— 与 guard 误报率**同一份 rubric**。
若两处各写一套「有据」标准，8.2 的有据率与需求方第 3 项的误报率就不可比、无法互相印证。

**口径（写清楚，避免以后对账混乱）**：
  1. 只对**含事实主张的答案**判分：`type ∈ {answer, low_confidence}`。
     拒答 / 澄清不含事实主张，把它们算进分母等于用「真空有据」抬高比例。
  2. 分两个数报，**不得混算**：
       * `llm 生成路径` —— 模型自由组织语言，是真正会被 guard 约束、也最可能越界的路径；
       * `全体答案`     —— 含 template 回落；template 由证据直接组装（构造上有据），
                          把它并进来会稀释 llm 路径的问题，故必须单独看 llm 那一档。
  3. 判官调用失败（`judge_error`）从分母**剔除并计数**，不得静默当成「有据」。
  4. 本轮 degraded（云端不可达等）的答案单列，不混入正常统计。

用法：
  .\.venv\Scripts\python.exe scripts/measure_grounded.py
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.llm.client import get_cloud_client  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402
from eval_judge import judge_answer  # noqa: E402

RAW_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-eval-raw.json"
OUT_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-grounded-raw.json"

ANSWER_TYPES = ("answer", "low_confidence")
_EV_FIELDS = ("kind", "content", "relation", "score", "source", "patch", "hero_ids")


def _to_evidence(items: list[dict]) -> list[Evidence]:
    return [Evidence(**{k: e.get(k) for k in _EV_FIELDS if k in e}) for e in items]


def _rate(rows: list[dict]) -> dict:
    """有据率 = grounded=True / (True + False)；judge_error 从分母剔除并单列。"""
    ok = [r for r in rows if r["judge"]["grounded"] is True]
    bad = [r for r in rows if r["judge"]["grounded"] is False]
    err = [r for r in rows if r["judge"]["grounded"] is None]
    denom = len(ok) + len(bad)
    return {"ok": len(ok), "bad": len(bad), "err": len(err), "denom": denom,
            "rate": (len(ok) / denom if denom else None)}


def main() -> None:
    if not RAW_JSON.exists():
        print(f"缺少 {RAW_JSON.name}（先跑 scripts/run_eval.py --set all）。")
        return
    client = get_cloud_client()
    if client is None:
        print("云端 LLM 未配置，无法判分（答案有据率需要 LLM 判官）。")
        return

    raw = json.loads(RAW_JSON.read_text(encoding="utf-8"))
    recs = [r for r in raw["records"] if r["type"] in ANSWER_TYPES and (r["answer"] or "").strip()]
    print("=" * 78)
    print("M6 答案有据率（LLM 判官；口径见模块头）")
    print("=" * 78)
    print(f"候选答案 {len(recs)} 条（type ∈ {ANSWER_TYPES}）")

    judged: list[dict] = []
    for i, r in enumerate(recs, 1):
        ev = _to_evidence(r["evidence"] or [])
        j = judge_answer(client, r["question"], ev, r["answer"])
        mode = (r["generation"] or {}).get("mode")
        judged.append({
            "case_id": r["case_id"], "set": r["set"], "turn": r["turn"],
            "question": r["question"], "mode": mode, "type": r["type"],
            "degraded": r["degraded"], "answer": r["answer"], "evidence": r["evidence"],
            "judge": j,
        })
        flag = "OK " if j["grounded"] is True else ("ERR" if j["grounded"] is False else "JUDGE?")
        print(f"  [{i:02d}] {flag} {r['case_id']}#{r['turn']} [{mode}/{r['type']}] "
              f"vt={j['violation_type']} {j['reason']}")
        if j["grounded"] is False:
            print(f"        答案：{r['answer'][:160]!r}")
            print(f"        无据片段：{j['unsupported']}")

    llm_rows = [r for r in judged if r["mode"] == "llm"]
    all_rows = judged
    normal = [r for r in judged if not r["degraded"]]
    llm_normal = [r for r in llm_rows if not r["degraded"]]

    print("\n" + "=" * 78)
    print("【答案有据率】")
    print("=" * 78)

    def show(label: str, rows: list[dict]) -> dict:
        s = _rate(rows)
        r = "n/a" if s["rate"] is None else f"{s['rate']:.1%}"
        print(f"  {label}：{s['ok']}/{s['denom']} = {r}"
              f"{f'（判官失败 {s['err']} 条已剔除分母）' if s['err'] else ''}")
        return s

    s_llm = show("llm 生成路径（非降级）", llm_normal)
    s_all = show("全体答案（非降级）", normal)
    if any(r["degraded"] for r in judged):
        show("降级答案（单列，不进主口径）", [r for r in judged if r["degraded"]])

    vt = Counter(r["judge"]["violation_type"] for r in judged)
    print(f"\n  越界类型分布：{dict(vt)}")
    print("\n  说明：判官是 LLM，不是独立第三方；对判 False 的每一条已附原文与无据片段，")
    print("        便于人工复核。判官与 guard 共用同一份 rubric（scripts/eval_judge.py）。")

    OUT_JSON.write_text(json.dumps({
        "candidates": len(recs),
        "llm": {"ok": s_llm["ok"], "denom": s_llm["denom"], "err": s_llm["err"]},
        "all": {"ok": s_all["ok"], "denom": s_all["denom"], "err": s_all["err"]},
        "violation_types": dict(vt),
        "rows": judged,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始记录已写入：{OUT_JSON.relative_to(PROJECT_ROOT)}")


main()
