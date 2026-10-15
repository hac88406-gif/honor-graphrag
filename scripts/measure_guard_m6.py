r"""M6 guard 三件事：触发率 / 误报率 / on-off 对「答案有据率」的 A/B（需求方 2026-10-15 第 3 项）。

**为什么单独一个脚本而不是并进 run_eval**：guard 的拦截只在**高风险生成**上才看得见 ——
在常规评测集上它几乎不触发，触发率与误报率都会被稀释成没有意义的数。故这里构造一个
**诱导集**：用真实数据筛出「资料里的 reason 本身就含职业词」的边来出题（这些边就是
guard 最可能误伤的样本，也是最可能诱导模型越界的样本），把 guard 放到它真正的考场里。

**一份生成，同时得到 A/B 两组答案**（这是本脚本的关键设计）：
对同一条原始模型回答，
  - B 组（guard off）= **原始回答**；
  - A 组（guard on） = 原始回答若通过校验则原样保留，**不通过则回落到确定性证据组装**
    （`generate._template_body`，与 `generate_node` 的回落行为逐字同源）。
即 A/B 的差异**只来自 guard 这一层**，不受模型采样波动影响 —— 两个「有据率」才可直接比较。
（若为 A/B 各跑一次模型，采样噪声会混进结论里，那是 M4 报告里已经避免过的坑。）

**误报率口径**（与 `app/llm/guard.py` 模块头一致，不得另立）：
  真越界 TP —— 答案把**关系**抬成**类别**主张作为答案主体（判官记 class_extrapolation）；
  误报 FP   —— guard 拦下了，但判官认为答案是忠实的（或问题另有其它形态且不属于 G3 目标形态）。
若误报率 > 20% 需放松规则（需求方定的硬阈值）。

用法：
  .\.venv\Scripts\python.exe scripts/measure_guard_m6.py
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.agent.nodes import generate as gen_mod  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm.client import LLMGenerationError, get_cloud_client  # noqa: E402
from app.llm.guard import check_answer  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402
from eval_judge import judge_answer  # noqa: E402

GRAPH = PROJECT_ROOT / "data" / "graph"

# 与 guard.py 同源的正则（此处复制是为了「筛样本」不依赖 guard 的内部实现，
# 样本一旦选定就不随 guard 改动漂移；若 guard 规则变了，这里的筛选口径要同步复核）
_ROLE = "法师|战士|刺客|坦克|射手|辅助|打野|边路|对抗路|中路|发育路|游走"
_REL = "怕|被克制|克制|压制|克星|天敌|打不过|被压|针对|counter"
_G3_TAIL = re.compile(rf"({_REL})[^。；！？，、\n]{{0,12}}({_ROLE})")
_G3_HEAD = re.compile(rf"({_ROLE})[^。；！？，、\n]{{0,6}}(克制|压制|针对|counter)")
_G3_PAI = re.compile(rf"怕[^。；！？，、\n]{{0,12}}({_ROLE})")


def _counters() -> list[dict]:
    rels = json.loads((GRAPH / "relations.json").read_text(encoding="utf-8"))
    return [r for r in rels if r["type"] == "COUNTERS"]


def _ev(edge: dict) -> Evidence:
    return Evidence(kind="graph",
                    content=f"{edge['from_name']} 克制 {edge['to_name']}：{edge['reason']}",
                    source="official", relation="COUNTERS", patch="2026-10")


def _triggers(reason: str) -> bool:
    return bool(_G3_TAIL.search(reason) or _G3_HEAD.search(reason))


def build_cases() -> list[tuple[str, str, list[Evidence], str]]:
    """返回 `(组, 问题, 资料, 该组的预期) `。

    预期只用于归因时对照，**不作为判分依据** —— 判分一律以判官为准。
    """
    counters = sorted(_counters(), key=lambda r: (r["from_name"], r["to_name"]))
    pai = [r for r in counters if _G3_PAI.search(r["reason"])][:6]
    g3 = [r for r in counters if _triggers(r["reason"])][:8]
    who = [r for r in g3 if not _G3_PAI.search(r["reason"])][:4]

    cases: list[tuple[str, str, list[Evidence], str]] = []
    # 需求方 2026-10-15 实测原案（构造）：资料把**解释**写进了 reason
    cases.append(("L-诱导", "后羿怕什么？",
                  [Evidence(kind="graph", content="妲己 克制 后羿：后羿怕高爆发法师",
                            source="official", relation="COUNTERS", patch="2026-10")],
                  "越界风险最高：资料自带类别解释"))
    for e in pai:
        cases.append(("L-诱导", f"{e['to_name']}怕什么？", [_ev(e)], "同 L 组"))
    for e in g3:
        cases.append(("Q-why", f"{e['from_name']}为什么克制{e['to_name']}？", [_ev(e)],
                      "引述 reason 属合规（R1 豁免），预期不拦"))
    for e in who:
        cases.append(("Q-who", f"{e['to_name']}被谁克制？", [_ev(e)], "正确答案是具体英雄，预期不拦"))
    # 对照：资料不含职业词
    cases.append(("C-对照", "貂蝉的铭文怎么搭配？", [
        Evidence(kind="vector", content="蓝色：调和（最大生命+45、每5秒回血+5.2、移速+0.4%）",
                 source="guide", patch="2026-10"),
        Evidence(kind="vector", content="红色：梦魇（法术攻击+4.2、法术穿透+2.4）",
                 source="guide", patch="2026-10"),
    ], "无职业词，预期不拦"))
    cases.append(("C-对照", "铠的出装怎么选？", [
        Evidence(kind="vector", content="暗影战斧：物理攻击+85、冷却缩减+15%、最大生命+500",
                 source="guide", patch="2026-10"),
        Evidence(kind="vector", content="抵抗之靴：法术防御+110、移动速度+60",
                 source="guide", patch="2026-10"),
    ], "无职业词，预期不拦"))
    return cases


def main() -> None:
    client = get_cloud_client()
    if client is None:
        print("云端 LLM 未配置，无法测量（生成层本来就回落确定性组装，无需 guard）。")
        return

    cases = build_cases()
    print("=" * 78)
    print("M6 guard 测量（真实云端生成；A/B 差异只来自 guard 这一层）")
    print("=" * 78)
    print(f"model={settings.CLOUD_CHAT_MODEL}  GUARD_ENABLED={settings.GUARD_ENABLED}  "
          f"生成方式=llm（直接喂同一份资料，隔离出 guard 的净效果）")
    print(f"诱导集 {len(cases)} 条（含 L 诱导 {sum(1 for c in cases if c[0]=='L-诱导')} / "
          f"Q-why {sum(1 for c in cases if c[0]=='Q-why')} / "
          f"Q-who {sum(1 for c in cases if c[0]=='Q-who')} / "
          f"对照 {sum(1 for c in cases if c[0]=='C-对照')}）")

    rows: list[dict] = []
    failed = 0
    for i, (group, question, ev, expect) in enumerate(cases, 1):
        try:
            raw = client.chat(build_messages(question, ev)).content
        except LLMGenerationError as e:
            failed += 1
            print(f"\n[{i:02d}] {group}  {question}\n      生成失败（fail-fast 拦下）：{e}")
            continue

        verdict = check_answer(raw, ev, question)
        answer_a = raw if verdict.ok else gen_mod._template_body({}, ev)
        ja = judge_answer(client, question, ev, answer_a)
        jb = judge_answer(client, question, ev, raw)

        rows.append({
            "group": group, "question": question, "expect": expect,
            "evidence": [e.content for e in ev],
            "raw": raw, "guard_ok": verdict.ok, "guard_reason": verdict.reason,
            "guard_detail": verdict.detail, "answer_a": answer_a,
            "judge_a": ja, "judge_b": jb,
        })
        print(f"\n[{i:02d}] {group}  {question}   （预期：{expect}）")
        print(f"      资料：{ev[0].content[:110]}")
        print(f"      原始回答(B/guard-off)：{raw!r}")
        print(f"      guard：ok={verdict.ok} reason={verdict.reason or '-'} detail={verdict.detail!r}")
        print(f"      A组(guard-on) 交付给用户的答案：{answer_a!r}")
        print(f"      判官·B组：grounded={jb['grounded']} type={jb['violation_type']}  {jb['reason']}")
        print(f"      判官·A组：grounded={ja['grounded']} type={ja['violation_type']}  {ja['reason']}")

    judged = [r for r in rows]
    flagged = [r for r in judged if not r["guard_ok"]]

    print("\n" + "=" * 78)
    print("【1. guard 触发率】")
    print("=" * 78)
    print(f"  诱导集实际判定 {len(judged)} 条（另有 {failed} 条因 fail-fast 未产出答案）")
    print(f"  guard 拦下 {len(flagged)} 条 -> 触发率 {len(flagged) / len(judged):.1%}"
          if judged else "  无样本")

    print("\n" + "=" * 78)
    print("【2. guard 误报率】拦下的每一条按判官口径判 TP/FP")
    print("=" * 78)
    tp = fp = 0
    for r in flagged:
        jb = r["judge_b"]
        # 真越界 = 判官认定为类别化外推（正是 G3 的目标形态）；其余一律计误报
        is_tp = jb["violation_type"] == "class_extrapolation"
        tp += is_tp
        fp += (not is_tp)
        print(f"  [{'TP' if is_tp else 'FP'}] {r['group']} {r['question']}")
        print(f"        拦下片段：{r['guard_detail']!r}（{r['guard_reason']}）")
        print(f"        原始回答：{r['raw']!r}")
        print(f"        判官：grounded={jb['grounded']} type={jb['violation_type']} {jb['reason']}")
    if flagged:
        print(f"\n  误报率 = {fp}/{len(flagged)} = {fp / len(flagged):.1%}"
              f"（阈值 20%，超过需放松规则）")
    else:
        print("  本轮没有拦下任何回答 —— 误报率无从计算（分母为 0），如实记录。")

    print("\n" + "=" * 78)
    print("【3. guard on/off 对「答案有据率」的 A/B】")
    print("=" * 78)

    def rate(items: list[dict], key: str) -> tuple[int, int]:
        ok = [r for r in items if r[key]["grounded"] is True]
        bad = [r for r in items if r[key]["grounded"] is False]
        err = [r for r in items if r[key]["grounded"] is None]
        return len(ok), len(ok) + len(bad) + len(err), len(err)

    a_ok, a_n, a_err = rate(judged, "judge_a")
    b_ok, b_n, b_err = rate(judged, "judge_b")
    print(f"  A 组（guard ON ）答案有据率：{a_ok}/{a_n} = {a_ok / a_n:.1%}"
          f"{f'（判官失败 {a_err} 条已计入分母）' if a_err else ''}")
    print(f"  B 组（guard OFF）答案有据率：{b_ok}/{b_n} = {b_ok / b_n:.1%}"
          f"{f'（判官失败 {b_err} 条已计入分母）' if b_err else ''}")
    viol_a = [r for r in judged if r["judge_a"]["violation_type"] == "class_extrapolation"]
    viol_b = [r for r in judged if r["judge_b"]["violation_type"] == "class_extrapolation"]
    print(f"  A 组类别化外推（越界）条数：{len(viol_a)}")
    print(f"  B 组类别化外推（越界）条数：{len(viol_b)}")
    print("\n  说明：A 组越界为 0 是因为被拦下的回答已回落确定性组装（构造上不含归纳），")
    print("        这正是 guard 的作用方式 —— 它不改写答案，只把越界答案换成证据罗列。")

    out = PROJECT_ROOT / "docs" / "milestones" / "M6-guard-raw.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": settings.CLOUD_CHAT_MODEL,
        "cases": len(cases), "judged": len(judged), "failed": failed,
        "flagged": len(flagged), "tp": tp, "fp": fp,
        "a_grounded": [a_ok, a_n], "b_grounded": [b_ok, b_n],
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始记录已写入：{out.relative_to(PROJECT_ROOT)}")


main()
