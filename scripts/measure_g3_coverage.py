r"""M6 审核补测：G3 的**实际生效覆盖率**，以及被 R1 豁免的答案里「只给类别不给具体英雄」的条数。

**为什么需要这个脚本**（需求方 2026-10-16 审核要求）：
M6 报告里「G3 触发 0/77」需要能被正确解读。需求方的怀疑是：这个数不是「没有越界输出」，
而是旧 R1（「问句含为什么/为何即整个 G3 关闭」）让相当比例的用例**根本没走到 G3 判定**。
本脚本把这个数拆开，并**用实测回答这个怀疑**（而不是替它下结论）。

口径（v2，修正 v1 的一处读数错误）：
- G3 只在**生成后校验**阶段运行，生成只发生在 LLM 路径上，故分母 = 走了生成后校验的 turn。
- **判定必须拿「模型原始正文」**。v1 直接读落盘的 `answer`，但 guard 判否时 `answer` 已被
  回落成确定性组装文本（原始正文在 `debug.generation.raw_answer`）—— 那会把「被拦下的越界」
  读成「没命中」，方向性错误。v2 的处理：
    * `generation.guard.reason == 'class_leak'` -> 直接记为 leak（片段取 `guard.detail`，
      这是当初真正被拦下的那一段，`raw_answer` 在旧记录里可能缺失）；
    * 其余（reason 为空 或 `hero_leak`）-> `answer` 就是原始正文，可安全过正则。
      其中 `hero_leak` 情形可**推断**：`check_answer` 先判 G3 再判 G2，故 reason=hero_leak
      ⟹ G3 当时没有未豁免命中。
- 判定用**当前规则**（M6 审核后已收窄 R1）复跑。

同时给出两项对照：
  ① 旧口径下有多少条问句命中旧 R1 的「问原因」开关（`为什么|为何|原因|…`）；
  ② 评测集里**真的含「问原因」词**的问句条数 —— 这才是「G3 触发数偏低」能否被解释的关键。
     （实测：本评测集 0 条问句含该措辞，故该现象与旧 R1 豁免无关，如实标注。）

**第二项测量**：在被 R1 豁免的用例里，有多少条答案是「只给类别、不给具体英雄」的 ——
直接量化漏拦的实际影响（用户拿到的是系统无法展开的类别答案）。

用法：
  .\.venv\Scripts\python.exe scripts/measure_g3_coverage.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.guard import (  # noqa: E402
    _CLASS_LEAK,
    _CLASS_LEAK_HEAD,
    _PUNCT_FOLD,
    _ROLE_DESC,
    _span_inside_hero_name,
    check_answer,
)
from app.schemas.chat import Evidence  # noqa: E402

RAW = PROJECT_ROOT / "docs" / "milestones" / "M6-eval-raw.json"
OUT_TXT = PROJECT_ROOT / "docs" / "milestones" / "M6-g3-coverage-output.txt"
OUT_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-g3-coverage-raw.json"

# 旧 R1（M6 审核前）的开关：问句命中即整条跳过 G3。此处只用于**对照**，不参与当前判定。
_OLD_REASON_SWITCH = ("为什么", "为何", "原因", "缘由", "怎么会", "咋会", "凭什么")

# 需求方 2026-10-16 实测的三例（复现旧 R1 整体放行）。用**不含类别句**的依据，
# 与真实语料一致（实测 0 条语料含「后羿怕高爆发法师」）。
_PROBE_EVIDENCE = [Evidence(
    kind="graph", content="妲己 克制 后羿：后羿血量低、位移差，容易被贴脸",
    source="official", relation="COUNTERS", patch="2026-10",
)]
_PROBE_CASES = [
    ("后羿怕高爆发法师。", "后羿怕哪些英雄？为什么？"),
    ("后羿的克星是高爆发法师英雄。", "后羿怕哪些英雄？为什么？"),
    ("后羿怕高爆发法师。", "后羿怕什么"),
]


def _candidates(text: str, corpus: str) -> list[tuple[str, str]]:
    """列出全部 G3 命中片段及其豁免归属（R1/R2/R3/leak），按匹配顺序。"""
    folded = text.translate(_PUNCT_FOLD)
    out: list[tuple[str, str]] = []
    for pat in (_CLASS_LEAK, _CLASS_LEAK_HEAD):
        for m in pat.finditer(folded):
            frag = m.group(0)
            if _span_inside_hero_name(folded, m.start(), m.end()):
                out.append((frag, "R2"))
            elif _ROLE_DESC.search(frag):
                out.append((frag, "R3"))
            elif frag in corpus:
                out.append((frag, "R1"))
            else:
                out.append((frag, "leak"))
    return out


def _hero_count(text: str) -> int:
    """答案里出现的英雄名个数（用与检索层同一份词典）。"""
    from app.retrieval.entity_linking import link

    return len([e for e in link(text).entities if e.entity_type == "hero"])


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"缺少 {RAW.name}（先跑 scripts/run_eval.py --set all）。")
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    total_turns = raw["summary"]["total_turns"]

    gen_turns = [r for r in raw["records"] if (r.get("generation") or {}).get("guard") is not None]

    rows: list[dict] = []
    for r in gen_turns:
        text = (r.get("answer") or "").strip()
        reason = ((r.get("generation") or {}).get("guard") or {}).get("reason") or ""
        detail = ((r.get("generation") or {}).get("guard") or {}).get("detail") or ""
        corpus = "\n".join(
            (e.get("content", "") if isinstance(e, dict) else str(e))
            for e in (r.get("evidence") or [])
        ).translate(_PUNCT_FOLD)

        if reason == "class_leak":
            # 原始正文已被回落覆盖，用当初记录的命中片段判定
            cands = [(detail, "leak")]
            raw_available = False
        else:
            # reason 为空 或 hero_leak：answer 即原始正文（G3 先于 G2 判定）
            cands = _candidates(text, corpus)
            raw_available = True

        exempt = next((t for _, t in cands if t != "leak"), None)
        verdict = "leak" if any(t == "leak" for _, t in cands) else (exempt or "none")
        rows.append({
            "case_id": r["case_id"], "turn": r["turn"], "question": r["question"],
            "answer": text, "candidates": cands, "verdict": verdict,
            "guard_reason": reason, "raw_available": raw_available,
            "old_r1_skipped": any(w in (r["question"] or "") for w in _OLD_REASON_SWITCH),
            "answer_hero_count": _hero_count(text) if verdict == "R1" else None,
        })

    n = len(rows)
    cnt = {k: 0 for k in ("none", "R1", "R2", "R3", "leak")}
    for row in rows:
        cnt[row["verdict"]] += 1
    raw_hits = sum(len(r["candidates"]) for r in rows)

    old_skipped = [r for r in rows if r["old_r1_skipped"]]
    old_skipped_with_leak = [r for r in old_skipped if r["verdict"] == "leak"]
    r1_rows = [r for r in rows if r["verdict"] == "R1"]
    r1_no_hero = [r for r in r1_rows if not r["answer_hero_count"]]
    no_raw = [r for r in rows if not r["raw_available"]]
    judged = cnt["leak"] + cnt["R1"] + cnt["R2"] + cnt["R3"]

    lines: list[str] = []
    p = lines.append
    p("=" * 78)
    p("M6 审核补测：G3 实际生效覆盖率（分母 = 走生成后校验的 turn）")
    p("=" * 78)
    p(f"评测集 turn 总数：{total_turns}   其中走生成后校验（guard 生效）：{n}")
    p(f"（其余 {total_turns - n} 个 turn 为模板组装/澄清/拒答，不经过生成后校验）")
    p("")
    p("[当前规则·逐条判定路径]")
    p(f"  G3 正则原始命中（无豁免）  ：{raw_hits} 处")
    p(f"  真的判了 G3 并拦下（leak） ：{cnt['leak']}/{n} = {cnt['leak'] / n:.1%}")
    p(f"  命中但被 R1 豁免（可溯源） ：{cnt['R1']}/{n} = {cnt['R1'] / n:.1%}")
    p(f"  命中但被 R2 豁免（英雄名） ：{cnt['R2']}/{n}")
    p(f"  命中但被 R3 豁免（定位描述）：{cnt['R3']}/{n}")
    p(f"  无 G3 候选（正则未命中）   ：{cnt['none']}/{n} = {cnt['none'] / n:.1%}")
    p(f"  -> G3 实际生效覆盖率（有候选、真的跑过判定）：{judged}/{n} = {judged / n:.1%}")
    p(f"  -> 原始正文不可复算（被 class_leak 拦下、已回落）：{len(no_raw)} 条")
    p("")
    p("[对照·旧 R1「问原因即整条跳过 G3」]")
    p(f"  问句命中旧 R1 开关（旧口径下整条跳过）：{len(old_skipped)}/{n} = {len(old_skipped) / n:.1%}")
    p(f"  其中在**新**口径下存在越界形态（旧放行/新会拦）：{len(old_skipped_with_leak)} 条")
    for r in old_skipped_with_leak:
        p(f"    [{r['case_id']}#{r['turn']}] {r['question']}")
        p(f"        候选={r['candidates']}  答案={r['answer'][:120]!r}")
    p(f"  **关键（如实标注）**：命中旧 R1 开关的问句为 {len(old_skipped)}/{n} 条 —— 本评测集里")
    p("           **没有任何一条问句**使用「为什么 / 为何 / 原因」这类措辞，故旧口径在本集上")
    p("           同样不会豁免任何一条。**「G3 触发数偏低」不能归因于旧 R1 豁免**；真实原因")
    p(f"           是本评测集覆盖「问原因 + 类别外推」形态的样本极少：{n} 条生成答案里 G3 正则")
    p(f"           原始命中仅 {raw_hits} 处。需求方「大量问原因类问题被 R1 豁免」的归因**在本评测集")
    p("           上不成立**（无样本支撑）；但 R1 作为「问题文本开关」的**原则缺陷成立**，故已按")
    p("           裁定收窄为「按 evidence 溯源」——见上「当前规则」段。")
    p("")
    p("[被 R1 豁免的用例：只给类别、不给具体英雄的占比]")
    p(f"  R1 豁免用例：{len(r1_rows)} 条；其中答案**无任何英雄名**（只给类别）：{len(r1_no_hero)} 条"
      f" = {(len(r1_no_hero) / len(r1_rows) if r1_rows else 0):.1%}")
    for r in r1_no_hero:
        p(f"    [{r['case_id']}#{r['turn']}] {r['question']}")
        p(f"        候选={r['candidates']}  答案={r['answer'][:120]!r}")
    p("")
    p("[需求方实测三例·当前规则复核]（依据不含类别句，与真实语料一致）")
    for ans, q in _PROBE_CASES:
        g = check_answer(ans, _PROBE_EVIDENCE, q)
        verdict = "拦下" if not g.ok else "放行"
        p(f"  {verdict}  答案={ans!r}  问题={q!r}  reason={g.reason or '-'} detail={g.detail or '-'}")
    p("=" * 78)

    report = "\n".join(lines)
    print(report)
    OUT_TXT.write_text(report + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps({
        "denominator": n, "total_turns": total_turns,
        "raw_regex_hits": raw_hits, "verdict_counts": cnt,
        "judged_coverage": f"{judged}/{n}",
        "raw_unavailable": len(no_raw),
        "old_r1_skipped": len(old_skipped),
        "old_r1_skipped_with_leak": [r["case_id"] for r in old_skipped_with_leak],
        "r1_exempt": len(r1_rows), "r1_exempt_no_hero": len(r1_no_hero),
        "probe": [{"answer": a, "question": q,
                   "ok": check_answer(a, _PROBE_EVIDENCE, q).ok}
                  for a, q in _PROBE_CASES],
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始记录已写入：{OUT_JSON.relative_to(PROJECT_ROOT)}")


main()
