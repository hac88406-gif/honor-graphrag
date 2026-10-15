r"""M4 前置：云端生成模型选型对比（deepseek-flash vs deepseek-v4-pro）。

需求方 2026-10-15 要求「先用 3~5 条真实问题在 flash / v4-pro 之间跑一次对比再定模型」，
本脚本把该对比做成可复跑的证据，结论写入 DECISIONS.md。

五个用例（资料全部取自本地快照 `data/graph/*.json`，不依赖 Neo4j）：
  1 铠被谁克制        —— 图谱 COUNTERS 入边 4 条（含官方 reason）
  2 铠怎么出装        —— item_sets 映射到 items.json 的真实装备名
  3 铠的铭文          —— ming_sets 映射到 inscriptions.json 的真实铭文名
  4 越界归纳复现      —— 需求方实测：资料写「妲己克制后羿，因后羿怕高爆发法师」，
                         模型答成「后羿怕高爆发法师，比如妲己」（把资料的**解释**当**类别**）
  5 资料不足          —— 只给无关资料，模型应说明不足而不是编造

另跑一组 max_tokens=200 复现需求方实测的「HTTP 200 + finish_reason=length + content 空串」，
用于固化「调用成功的判定 = content 非空 AND finish_reason != 'length'」。

用法（需 .env 内 CLOUD_API_KEY 可用）：
  python scripts/compare_llm_models.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402

GRAPH = PROJECT_ROOT / "data" / "graph"

# 4.9 生成约束的基础版（M3/M4 用的那套）
SYSTEM_BASE = (
    "你是王者荣耀攻略助手。只能依据【资料】回答，不得引入资料之外的事实、数值或英雄名。"
    "资料不足以回答时，直接说明资料不足。"
)
# 强化版：显式禁止「归纳/外推/把解释当类别」——用于验证「光靠 prompt 够不够」
SYSTEM_HARDENED = SYSTEM_BASE + (
    "严禁归纳、外推或改写：资料里对某条关系的**解释**不得当成该类英雄的**类别**来表述；"
    "不得新增资料未出现的英雄名或数值。"
)


def _load() -> tuple[dict, dict, list, dict]:
    heroes = json.loads((GRAPH / "heroes.json").read_text(encoding="utf-8"))
    items = {i["id"]: i["name"] for i in json.loads((GRAPH / "items.json").read_text(encoding="utf-8"))}
    inscriptions = {i["id"]: i for i in json.loads((GRAPH / "inscriptions.json").read_text(encoding="utf-8"))}
    rels = json.loads((GRAPH / "relations.json").read_text(encoding="utf-8"))
    return {h["name"]: h for h in heroes}, items, rels, inscriptions


def _cases() -> list[dict]:
    by_name, items, rels, ins = _load()

    # 1 铠被谁克制：COUNTERS 入边（to_name == 铠）
    counters = [r for r in rels if r["type"] == "COUNTERS" and r["to_name"] == "铠"]
    ev1 = "\n".join(f"- {r['from_name']} 克制 铠：{r['reason']}" for r in counters[:4])

    # 2 铠怎么出装：item_sets[0] -> 装备名
    kai = by_name["铠"]
    ev2 = "\n".join(f"- {items.get(i, i)}" for i in kai["item_sets"][0])

    # 3 铠的铭文：ming_sets[0] -> 铭文名 + 属性
    ev3 = "\n".join(f"- {ins[i]['color']}：{ins[i]['name']}（{ins[i]['des']}）" for i in kai["ming_sets"][0])

    return [
        {
            "key": "1-克制",
            "question": "铠被谁克制？",
            "evidence": ev1,
            "system": SYSTEM_BASE,
        },
        {
            "key": "2-出装",
            "question": "铠怎么出装？",
            "evidence": ev2,
            "system": SYSTEM_BASE,
        },
        {
            "key": "3-铭文",
            "question": "铠的铭文怎么搭配？",
            "evidence": ev3,
            "system": SYSTEM_BASE,
        },
        {
            "key": "4a-越界·基础prompt",
            "question": "后羿怕什么？",
            "evidence": "- 妲己 克制 后羿：后羿怕高爆发法师",
            "system": SYSTEM_BASE,
        },
        {
            "key": "4b-越界·强化prompt",
            "question": "后羿怕什么？",
            "evidence": "- 妲己 克制 后羿：后羿怕高爆发法师",
            "system": SYSTEM_HARDENED,
        },
        {
            "key": "5-资料不足",
            "question": "铠被谁克制？",
            "evidence": "- 铁剑：价格 275（攻击类装备）",
            "system": SYSTEM_BASE,
        },
    ]


def _call(model: str, case: dict, *, max_tokens: int | None = None) -> dict:
    url = settings.CLOUD_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": case["system"]},
            {"role": "user", "content": f"【资料】\n{case['evidence']}\n\n【问题】{case['question']}"},
        ],
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        "stream": False,
    }
    t0 = time.perf_counter()
    with httpx.Client(timeout=settings.LLM_TIMEOUT) as c:
        r = c.post(url, json=payload, headers={"Authorization": f"Bearer {settings.CLOUD_API_KEY}"})
    dt = time.perf_counter() - t0

    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    usage = body.get("usage") or {}
    return {
        "http": r.status_code,
        "latency": round(dt, 2),
        "content": content,
        "content_len": len(content),
        "empty": not content.strip(),
        "finish": choice.get("finish_reason"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_len": len(reasoning),
        "reasoning": reasoning,
    }


# 越界归纳的启发式标记：把资料里的**解释**当成**类别**来答
_LEAK = re.compile(r"怕[^。；\n]{0,8}(法师|战士|刺客|坦克|射手|辅助)")


def main() -> None:
    models = [settings.CLOUD_CHAT_MODEL, "deepseek-flash"]
    cases = _cases()

    print("=" * 96)
    print(f"云端模型对比   base={settings.CLOUD_BASE_URL}   max_tokens={settings.LLM_MAX_TOKENS}")
    print("=" * 96)
    print(f"{'模型':<18}{'用例':<20}{'HTTP':<6}{'耗时s':<7}{'答案字数':<9}{'finish':<10}{'completion_tokens':<18}{'reasoning字'}")
    print("-" * 96)

    raw: dict[str, dict] = {}
    for m in models:
        for c in cases:
            res = _call(m, c)
            raw[f"{m}|{c['key']}"] = res
            print(
                f"{m:<18}{c['key']:<20}{res['http']:<6}{res['latency']:<7}"
                f"{res['content_len']:<9}{str(res['finish']):<10}{str(res['completion_tokens']):<18}{res['reasoning_len']}"
            )

    print("\n" + "=" * 96)
    print("越界归纳复现（用例 4a/4b）——答案原文")
    print("=" * 96)
    for m in models:
        for key in ("4a-越界·基础prompt", "4b-越界·强化prompt"):
            res = raw[f"{m}|{key}"]
            leaked = bool(_LEAK.search(res["content"]))
            print(f"\n[{m} / {key}] 启发式判定=把解释当类别: {'是' if leaked else '否'}")
            print(f"  {res['content'][:300]!r}")

    print("\n" + "=" * 96)
    print("资料不足（用例 5）——答案原文（应说明不足，不得编造克制对象）")
    print("=" * 96)
    for m in models:
        res = raw[f"{m}|5-资料不足"]
        print(f"\n[{m}] {res['content'][:300]!r}")

    print("\n" + "=" * 96)
    print("空答案复现（max_tokens=200）——用于固化「成功判定 = content 非空 AND finish != length」")
    print("  注：思考吃掉的 token 随问题复杂度上升；短问题（用例 1）在 200 下不一定触发，重问题（用例 3）才暴露")
    print("=" * 96)
    for m in models:
        for idx, label in ((0, "1-克制(短)"), (2, "3-铭文(重)")):
            res = _call(m, cases[idx], max_tokens=200)
            print(
                f"[{m} / {label}] HTTP={res['http']} finish={res['finish']} "
                f"completion_tokens={res['completion_tokens']} content_len={res['content_len']} "
                f"empty={res['empty']} reasoning_len={res['reasoning_len']}"
            )
            print(f"  content={res['content'][:120]!r}")

    print("\n" + "=" * 96)
    print("汇总：三档检查")
    print("=" * 96)
    for m in models:
        rows = [raw[f"{m}|{c['key']}"] for c in cases]
        ok = sum(1 for r in rows if r["http"] == 200 and not r["empty"] and r["finish"] != "length")
        tok = [r["completion_tokens"] for r in rows if r["completion_tokens"]]
        lat = [r["latency"] for r in rows]
        print(
            f"{m:<18} 合格 {ok}/{len(rows)}   completion_tokens 均值 {sum(tok) // len(tok)} "
            f"(min {min(tok)} / max {max(tok)})   耗时均值 {round(sum(lat) / len(lat), 2)}s"
        )


main()
