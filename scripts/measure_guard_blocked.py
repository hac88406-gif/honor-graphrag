r"""M6 guard 误报率（生产路径口径）—— 判定**常规评测集里真正被拦下**的回答是 TP 还是 FP。

**为什么需要这个脚本**：`measure_guard_m6.py` 的诱导集本轮 0 触发，`measure_guard_fp.py`
的受控集在**当前规则**下同样 0 拦下 —— 两处误报率的分母都是 0。而 8.2 要的是
「抽检**被拦下**的回答判 TP/FP」，真正被拦下的样本落在常规跑批里，故回到
`M6-eval-raw.json` 把它们捞出来单独判。

**判的是哪一份文本（M6 修订，务必看清）**：
`app/agent/nodes/generate.py` 现在会在 guard 判否时把**被拦下的原始正文**写进
`debug.generation.raw_answer`，所以本脚本直接判**当初真正被拦下的那一段**（`source=captured`）。
此前版本因原文未留存，只能「同题同资料重新生成一次再判」，而重采样常复现不出当初那句话，
会把真越界记成误报 —— 该近似点已随留痕落地消除。仅当遇到**旧记录**（无 `raw_answer` 字段）
时才回退到重采样，并在记录里标 `source=resampled`，绝不把两者混算。

**判据**：
  TP（拦得对）—— 判官认为该答案**不完全忠实于资料**（`grounded=False`，任一越界类型）；
                  guard 虽用规则命中，但命中的确实是越界文本。
  FP（误报）  —— 判官认为该答案**完全忠实于资料**（`grounded=True` / `violation_type=none`），
                  guard 却把合规回答拦下并降级成机械罗列 —— 这正是需求方要压制的代价。
  判官调用失败（`judge_error`）**从分母剔除并计数**，不得静默算作 FP。

用法：
  .\.venv\Scripts\python.exe scripts/measure_guard_blocked.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.llm.client import LLMGenerationError, get_cloud_client  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402
from eval_judge import judge_answer  # noqa: E402

RAW = PROJECT_ROOT / "docs" / "milestones" / "M6-eval-raw.json"
OUT = PROJECT_ROOT / "docs" / "milestones" / "M6-guard-blocked-raw.json"
_EV = ("kind", "content", "relation", "score", "source", "patch", "hero_ids")


def _blocked_records() -> list[dict]:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    out = []
    for r in raw["records"]:
        g = (r["generation"] or {}).get("guard")
        if g and not g.get("ok"):
            out.append(r)
    return out


def main() -> None:
    client = get_cloud_client()
    if client is None:
        print("云端 LLM 未配置，无法判定。")
        return
    if not RAW.exists():
        print(f"缺少 {RAW.name}（先跑 scripts/run_eval.py --set all）。")
        return

    blocked = _blocked_records()
    print("=" * 78)
    print("M6 guard 误报率（生产路径：常规评测集真正被拦下的回答）")
    print("=" * 78)
    if not blocked:
        print("本轮评测集里没有 guard 拦下的样本 —— 分母为 0，误报率无从计算（如实记录）。")
        OUT.write_text(json.dumps({"blocked": 0, "judged": 0, "tp": 0, "fp": 0, "rows": []},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return
    print(f"被拦下 {len(blocked)} 条\n")

    rows: list[dict] = []
    tp = fp = err = 0
    captured = resampled = 0
    for r in blocked:
        g = r["generation"]["guard"]
        ev = [Evidence(**{k: e.get(k) for k in _EV if k in e}) for e in (r["evidence"] or [])]
        q = r["question"]
        print(f"[{r['case_id']}#{r['turn']}] {q}")
        print(f"  guard 拦下：{g['reason']}  detail={g['detail']!r}")
        print(f"  交付答案（已回落确定性组装）：{r['answer'][:140]!r}")

        raw_answer = (r["generation"] or {}).get("raw_answer")
        if raw_answer:
            judged_text, source = raw_answer, "captured"
            captured += 1
            print(f"  被拦下的原始正文（留痕）：{judged_text!r}")
        else:
            # 旧记录没有留痕：回退重采样，并在输出里明确标注，不与 captured 混算。
            source = "resampled"
            resampled += 1
            try:
                judged_text = client.chat(build_messages(q, ev)).content
            except LLMGenerationError as e:
                print(f"  重新生成失败（fail-fast）：{e} -> 无答案可判，剔除分母\n")
                continue
            print(f"  ⚠ 原始正文未留痕，回退同题重采样：{judged_text!r}")

        j = judge_answer(client, q, ev, judged_text)
        if j["grounded"] is None:   # 判官失败：剔除分母并计数，不算 FP
            err += 1
            print(f"  判官失败（剔除分母）：{j['reason']}\n")
            rows.append({"case_id": r["case_id"], "turn": r["turn"], "question": q,
                         "guard": g, "source": source, "judged_text": judged_text,
                         "judge": j, "verdict": "judge_error"})
            continue

        is_fp = j["grounded"] is True
        tp += (not is_fp)
        fp += is_fp
        print(f"  判官：grounded={j['grounded']} type={j['violation_type']}  {j['reason']}")
        print(f"  -> [{'FP' if is_fp else 'TP'}]\n")
        rows.append({"case_id": r["case_id"], "turn": r["turn"], "question": q,
                     "guard": g, "source": source, "judged_text": judged_text,
                     "delivered": r["answer"], "judge": j,
                     "verdict": "FP" if is_fp else "TP"})

    n = tp + fp
    print("=" * 78)
    print(f"判定来源：留痕原文 {captured} 条 / 重采样 {resampled} 条"
          f"{f' / 判官失败剔除 {err} 条' if err else ''}")
    if n:
        print(f"误报率 = {fp}/{n} = {fp / n:.1%}（阈值 20%，超过需放松规则）")
    else:
        print("可判样本为 0 —— 误报率无从计算（如实记录）")
    print("=" * 78)

    OUT.write_text(json.dumps({"blocked": len(blocked), "judged": n, "tp": tp, "fp": fp,
                               "judge_error": err, "captured": captured,
                               "resampled": resampled, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始记录已写入：{OUT.relative_to(PROJECT_ROOT)}")


main()
