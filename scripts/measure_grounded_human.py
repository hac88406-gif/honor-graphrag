r"""M6 答案有据率 —— **人工抽检臂**（规格书 8.2：LLM-as-judge + 人工抽检各 50%）。

**为什么必须有这一臂**：`measure_grounded.py` 用的是 LLM 判官，而判官**不是独立第三方**
（与 guard 共用同一份 rubric，自身也有噪声）。8.2 明确要求**一半样本由人工复核**，
本脚本负责把那一半样本导出成「问题 + 答案 + 依据 + 判官意见」的复核工作表，
供逐条**独立判定**（先看依据判，再看判官意见核对，避免被判官带偏）。

**为什么抽样必须是确定性的**：随机抽样不可复跑——换一次样本比例就守不住，
和本项目「指标必须可复算」的取向相悖。故按候选答案的**行序奇偶**固定切分：
偶数行 → 人工臂，奇数行 → LLM 判官臂（判官臂沿用 `measure_grounded.py` 的结果）。

**依据为什么要截断**：工作表要能被人一眼扫完；每段依据截到 `EV_CHARS` 字符、最多 `EV_MAX` 段。
截断只影响**工作表可读性**，不改变判定口径——凡被截断的条目在工作表里标注 `…`，
人工复核时若对某条存疑，可回 `M6-grounded-raw.json` 看全文。

用法：
  .\.venv\Scripts\python.exe scripts/measure_grounded_human.py
输出：docs/milestones/M6-grounded-human-sample.txt
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_JSON = PROJECT_ROOT / "docs" / "milestones" / "M6-grounded-raw.json"
OUT_TXT = PROJECT_ROOT / "docs" / "milestones" / "M6-grounded-human-sample.txt"

EV_CHARS = 220
EV_MAX = 3
ANS_CHARS = 500


def _trunc(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def main() -> None:
    if not RAW_JSON.exists():
        print(f"缺少 {RAW_JSON.name}（先跑 scripts/measure_grounded.py）。")
        return
    data = json.loads(RAW_JSON.read_text(encoding="utf-8"))
    rows: list[dict] = data["rows"]

    human = [r for i, r in enumerate(rows) if i % 2 == 0]
    llm_arm = [r for i, r in enumerate(rows) if i % 2 == 1]

    def rate(arm: list[dict]) -> tuple[int, int, int]:
        ok = sum(1 for r in arm if r["judge"]["grounded"] is True)
        bad = sum(1 for r in arm if r["judge"]["grounded"] is False)
        err = sum(1 for r in arm if r["judge"]["grounded"] is None)
        return ok, ok + bad, err

    ok_l, den_l, err_l = rate(llm_arm)
    print(f"候选 {len(rows)} 条 → 人工臂 {len(human)} 条 / LLM 判官臂 {len(llm_arm)} 条")
    print(f"[参考] LLM 判官臂（奇数行）：{ok_l}/{den_l} = {ok_l / den_l:.1%}（判官失败 {err_l} 条剔除）")

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("M6 答案有据率 · 人工抽检臂工作表（规格书 8.2：人工复核 50% 样本）")
    lines.append("=" * 78)
    lines.append(f"候选答案 {len(rows)} 条（type ∈ answer/low_confidence）→ 本表含 {len(human)} 条（偶数行）")
    lines.append("判定口径：答案的**每个事实性陈述**是否都能在【依据】中找到出处。")
    lines.append("  判 grounded=是：全部可溯源 / 只声明资料不足。")
    lines.append("  判 grounded=否：出现依据外的事实、英雄/装备名，或把解释抬成类别。")
    lines.append("每块末尾附【判官意见】供交叉核对——请**先依据判**，再看判官，避免被带偏。")
    lines.append("")
    for n, r in enumerate(human, 1):
        lines.append("-" * 78)
        lines.append(f"[H{n:02d}] {r['case_id']}#{r['turn']}  set={r['set']}  mode={r['mode']}  "
                     f"type={r['type']}  degraded={r['degraded']}")
        lines.append(f"  问题：{r['question']}")
        lines.append(f"  答案：{_trunc(r['answer'], ANS_CHARS)}")
        ev = r.get("evidence") or []
        if not ev:
            lines.append("  依据：（无）")
        else:
            lines.append(f"  依据（{len(ev)} 段，展示前 {min(len(ev), EV_MAX)} 段）：")
            for e in ev[:EV_MAX]:
                tag = e.get("kind") or e.get("source") or "?"
                lines.append(f"    - [{tag}] {_trunc(e.get('content'), EV_CHARS)}")
            if len(ev) > EV_MAX:
                lines.append(f"    …（其余 {len(ev) - EV_MAX} 段略，全文见 M6-grounded-raw.json）")
        j = r["judge"]
        lines.append(f"  【判官意见】grounded={j['grounded']}  vt={j['violation_type']}  {j['reason']}")
        lines.append("  【人工判定】grounded=____  说明：")
        lines.append("")
    lines.append("=" * 78)
    lines.append(f"人工臂共 {len(human)} 条待判；判完把结论回填到 docs/eval_report.md §2.4 与 §2.6 说明。")

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"工作表已写入：{OUT_TXT.relative_to(PROJECT_ROOT)}")


main()
