r"""guard 误报率测量（M4 二审裁定 B-1，需求方 2026-10-15）。

**要回答的问题**：guard 的 G3（类别化外推）是**正则**匹配，可能误伤正常回答 ——
官方 reason 本身含「刺客/射手/法师」这类职业词时（实测 `relations.json` 里**大量存在**），
模型**正当引用**这条 reason 会不会被拦？

**测例不是手编的，是从真实数据里筛出来的**：先用 G3 的正则去扫 `relations.json` 的
COUNTERS reason，筛出「reason 本身就会触发 G3」的边 —— 这些边就是误报风险最高的样本，
拿它们出题才测得到真东西。

**判定口径（判官口径，必须一致，否则比例没有意义）**：
  真越界（TP）—— 答案把**关系**抬成**类别**主张，作为答案主体交付
                （如问「后羿怕什么」答「后羿怕高爆发法师」）；
  误报（FP）  —— 答案的主主张仍是**资料里的具体关系**，职业词只出现在**忠实引述**的
                原因从句里（如问「东皇为什么克制司马懿」答「因为硬控能克制刺客的突袭」）。

**两条规则对照（关键）**：脚本对**同一批模型回答**同时给出
「放松前规则（仅 G3 正则，无豁免）」与「当前规则（R1/R2 豁免 + 括号折叠）」的拦下结果。
两条规则跑同样的答案，差异只来自规则本身，不受模型采样波动影响 —— 两个误报率才可直接比较。

**这不是单测**：需要真实云端生成，故单独成脚本，结论写入 M4 报告。

用法：`python scripts/measure_guard_fp.py`
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.llm.client import LLMGenerationError, get_cloud_client  # noqa: E402
from app.llm.guard import check_answer  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402

GRAPH = PROJECT_ROOT / "data" / "graph"
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

# 与 guard.py 保持一致的正则（此处**复制**而非 import，是为了让「筛样本」这一步
# 不依赖 guard 的内部实现细节；若 guard 改了规则，这里要同步改，否则样本会失真）
_ROLE = "法师|战士|刺客|坦克|射手|辅助|打野|边路|对抗路|中路|发育路|游走"
_REL = "怕|被克制|克制|压制|克星|天敌|打不过|被压|针对|counter"
_G3_TAIL = re.compile(rf"({_REL})[^。；！？，、\n]{{0,12}}({_ROLE})")
_G3_HEAD = re.compile(rf"({_ROLE})[^。；！？，、\n]{{0,6}}(克制|压制|针对|counter)")
_G3_PAI = re.compile(rf"怕[^。；！？，、\n]{{0,12}}({_ROLE})")

# 需求方 2026-10-15 实测原案（构造）：资料把**解释**写在了 reason 里
USER_CASE = [Evidence(kind="graph", content="妲己 克制 后羿：后羿怕高爆发法师",
                      source="official", relation="COUNTERS", patch="2026-10")]


def _all_counters() -> list[dict]:
    rels = json.loads((GRAPH / "relations.json").read_text(encoding="utf-8"))
    return [r for r in rels if r["type"] == "COUNTERS"]


def _ev(edge: dict) -> Evidence:
    return Evidence(kind="graph",
                    content=f"{edge['from_name']} 克制 {edge['to_name']}：{edge['reason']}",
                    source="official", relation="COUNTERS", patch="2026-10")


def _triggers_g3(reason: str) -> bool:
    return bool(_G3_TAIL.search(reason) or _G3_HEAD.search(reason))


def _raw_g3_flag(answer: str) -> str | None:
    """**放松前**的规则（仅 G3 正则，无 R1/R2 豁免、无括号折叠）会否拦下该答案。

    用于在**同一批模型回答**上对照「放松前 / 放松后」两条规则的拦下数 ——
    两条规则跑同样的答案，差异只来自规则本身，不受模型采样波动影响，比例才可比。
    """
    for pat in (_G3_TAIL, _G3_HEAD):
        m = pat.search(answer)
        if m:
            return m.group(0)
    return None


def build_cases() -> list[tuple[str, str, list[Evidence]]]:
    """从真实数据筛测例：
      L      —— reason 直接写出「怕 + 职业」的边，问「{to}怕什么」（诱导类别化回答）
      Q-why  —— reason 触发 G3 的边，问「{from}为什么克制{to}」（模型会**正当引用** reason，误报风险最高）
      Q-who  —— 同一批边，问「{to}被谁克制」（正确答案是具体英雄，预期不拦）
      C      —— 对照：资料不含职业词
    """
    counters = sorted(_all_counters(), key=lambda r: (r["from_name"], r["to_name"]))
    pai_edges = [r for r in counters if _G3_PAI.search(r["reason"])][:3]
    g3_edges = [r for r in counters if _triggers_g3(r["reason"])][:6]
    # Q-who 用「reason 含职业词但没写出『怕+职业』」的边，避免与 L 组重复
    who_edges = [r for r in g3_edges if not _G3_PAI.search(r["reason"])][:4]

    cases: list[tuple[str, str, list[Evidence]]] = []
    cases.append(("L", "后羿怕什么？", USER_CASE))
    for e in pai_edges:
        cases.append(("L", f"{e['to_name']}怕什么？", [_ev(e)]))
    for e in g3_edges:
        cases.append(("Q-why", f"{e['from_name']}为什么克制{e['to_name']}？", [_ev(e)]))
    for e in who_edges:
        cases.append(("Q-who", f"{e['to_name']}被谁克制？", [_ev(e)]))
    cases.append(("C", "貂蝉的铭文怎么搭配？", [
        Evidence(kind="vector", content="蓝色：调和（最大生命+45、每5秒回血+5.2、移速+0.4%）",
                 source="guide", patch="2026-10"),
        Evidence(kind="vector", content="红色：梦魇（法术攻击+4.2、法术穿透+2.4）",
                 source="guide", patch="2026-10"),
    ]))
    cases.append(("C", "铠的出装怎么选？", [
        Evidence(kind="vector", content="暗影战斧：物理攻击+85、冷却缩减+15%、最大生命+500",
                 source="guide", patch="2026-10"),
        Evidence(kind="vector", content="抵抗之靴：法术防御+110、移动速度+60",
                 source="guide", patch="2026-10"),
    ]))
    return cases


def main() -> None:
    client = get_cloud_client()
    if client is None:
        print("云端 LLM 未配置，无法测量。")
        return

    counters = _all_counters()
    g3_hits = [r for r in counters if _triggers_g3(r["reason"])]
    cases = build_cases()

    print("=" * 78)
    print("guard 误报率测量（真实云端，判定口径见脚本头）")
    print("=" * 78)
    print(f"model={settings.CLOUD_CHAT_MODEL}")
    print(f"COUNTERS 共 {len(counters)} 条，其中 reason 本身就会触发 G3 的 = {len(g3_hits)} 条"
          f"（{len(g3_hits) / len(counters):.0%}）—— 这就是误报风险样本池")
    print(f"本次测例 {len(cases)} 条")

    flagged = 0
    raw_flagged = 0
    failed = 0
    for i, (group, question, ev) in enumerate(cases, 1):
        try:
            result = client.chat(build_messages(question, ev))
        except LLMGenerationError as e:
            # 调用失败（如空答案被 fail-fast 拦下）-> 没有答案可供 guard 判定，不计入分母。
            # 这本身就是 M4 空答案防线在真实运行中生效的证据。
            failed += 1
            print(f"\n[{i:02d}] 组={group}  问题：{question}")
            print(f"      生成失败（fail-fast）：{e}  -> 节点回落确定性组装，用户不会看到空答案")
            continue

        verdict = check_answer(result.content, ev, question)
        raw = _raw_g3_flag(result.content)
        if not verdict.ok:
            flagged += 1
        if raw:
            raw_flagged += 1

        print(f"\n[{i:02d}] 组={group}  问题：{question}")
        for e in ev:
            print(f"      资料：{e.content[:120]}")
        print(f"      原文：{result.content!r}")
        print(f"      放松前规则（仅 G3 正则，无豁免）：{'拦下 ' + raw if raw else '放行'}")
        print(f"      当前规则（R1/R2 豁免 + 括号折叠）：ok={verdict.ok}  "
              f"reason={verdict.reason or '-'}  detail={verdict.detail!r}")
        print("      判定：待人工按口径分类（TP / FP）")

    judged = len(cases) - failed
    print("\n" + "=" * 78)
    print(f"合计：{len(cases)} 例，生成失败（fail-fast 拦下）{failed} 例，实际判定 {judged} 例")
    print(f"  放松前规则拦下 {raw_flagged} 例（{raw_flagged / judged:.0%} of 判定数）")
    print(f"  当前规则拦下 {flagged} 例（{flagged / judged:.0%} of 判定数）")
    print("两条规则跑的是**同一批模型回答**，差异只来自规则本身（不受采样波动影响）。")
    print("拦下例的 TP/FP 比例按脚本头口径逐例判定 —— 见 M4 报告 §3.5。")
    print("=" * 78)


main()
