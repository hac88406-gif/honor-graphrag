r"""M6 审核补测：首 token 延迟的**模型对比**（deepseek-chat vs deepseek-v4-pro）。

**要回答的问题**（需求方 2026-10-16 修正要求）：
M6 报告把首 token 未达标（mean 4.22s）的根因登记为「校验优先于观感」。但**句级增量校验实测收益
0.00s** 恰恰说明主因不在校验，而在**推理模型的思考前置** —— v4-pro 先吐 250~290 token 的
reasoning_content，正文在其后才产生，首 token 被**思考时间**主导。
本脚本用同一批**真实问句 + 真实依据**（取自 `M6-eval-raw.json` 里走 LLM 生成的记录，不重新检索），
在 chat（实测 reasoning=0）与 v4-pro 之间做对照，判定 4.22s 是「设计取舍」还是「选型问题」。

口径：
- 首 token = 首个**正文**分片（content delta）的时间戳；另单列首个 reasoning 分片时间戳。
- 生成 prompt 与生产路径**完全一致**（`app.llm.prompts.build_messages`），只替换模型名。
- 答案有据率沿用 M6 同一份判官 rubric（`scripts/eval_judge.judge_answer`），判官模型仍取
  `.env` 的 `CLOUD_CHAT_MODEL`（不因被测模型改变而改变判据）。

用法（需 .env 内 CLOUD_API_KEY 可用）：
  .\.venv\Scripts\python.exe scripts/compare_first_token_models.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm.client import get_cloud_client  # noqa: E402
from app.llm.prompts import build_messages  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402
from eval_judge import judge_answer  # noqa: E402

RAW = PROJECT_ROOT / "docs" / "milestones" / "M6-eval-raw.json"
OUT = PROJECT_ROOT / "docs" / "milestones" / "M6-firsttoken-model-compare-output.txt"

MODELS = ["deepseek-chat", "deepseek-v4-pro"]

# 采样：按意图各取一条（避免全落在同一形态），只取走 LLM 生成且有依据的记录
_WANTED_INTENTS = ["COUNTER_BY", "ITEM_BUILD", "INSCRIPTION", "SYNERGY", "GAMEPLAY", "TIER_META", "MATCHUP"]


def _pick() -> list[dict]:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    out: list[dict] = []
    for intent in _WANTED_INTENTS:
        for r in raw["records"]:
            if r.get("intent") != intent:
                continue
            if (r.get("generation") or {}).get("mode") != "llm":
                continue
            if not (r.get("evidence") or []):
                continue
            if r.get("type") not in ("answer", "low_confidence"):
                continue
            out.append(r)
            break
    return out


def _stream_timed(model: str, messages: list[dict]) -> dict:
    """逐分片打时间戳：首个 reasoning 分片 / 首个正文分片 / 全文完成 + token 用量。"""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {"Authorization": f"Bearer {settings.CLOUD_API_KEY}", "Content-Type": "application/json"}
    t0 = time.perf_counter()
    content = reasoning = ""
    first_reasoning = first_content = full = None
    finish = None
    usage: dict = {}
    with httpx.stream(
        "POST", f"{settings.CLOUD_BASE_URL.rstrip('/')}/chat/completions",
        json=payload, headers=headers, timeout=settings.LLM_TIMEOUT,
    ) as resp:
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
            if obj.get("usage"):
                usage = obj["usage"]
            choice = (obj.get("choices") or [{}])[0]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning += delta["reasoning_content"]
                if first_reasoning is None:
                    first_reasoning = time.perf_counter() - t0
            if delta.get("content"):
                content += delta["content"]
                if first_content is None:
                    first_content = time.perf_counter() - t0
    if full is None:
        full = time.perf_counter() - t0
    details = usage.get("completion_tokens_details") or {}
    return {
        "first_reasoning_s": round(first_reasoning, 3) if first_reasoning else None,
        "first_token_s": round(first_content, 3) if first_content else None,
        "full_s": round(full, 3),
        "finish_reason": finish,
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "reasoning_chars": len(reasoning),
        "content": content,
        "content_len": len(content),
    }


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"缺少 {RAW.name}（先跑 scripts/run_eval.py --set all）。")
    cases = _pick()
    judge_client = get_cloud_client()
    if judge_client is None:
        raise SystemExit("云端未配置，无法判分。")

    lines: list[str] = []
    p = lines.append
    p("=" * 100)
    p(f"首 token 模型对比（同一批真实问句+真实依据）  base={settings.CLOUD_BASE_URL}")
    p(f"判官模型 = {settings.CLOUD_CHAT_MODEL}（判据不随被测模型改变）")
    p("=" * 100)
    p(f"{'模型':<18}{'用例':<10}{'意图':<12}{'首个思考s':<11}{'首token s':<11}{'完整s':<9}"
      f"{'completion':<12}{'reasoning_tok':<14}{'正文长':<8}{'有据'}")
    p("-" * 100)

    per_model: dict[str, list[dict]] = {m: [] for m in MODELS}
    for m in MODELS:
        for r in cases:
            evidence = [Evidence(**e) for e in r["evidence"]]
            res = _stream_timed(m, build_messages(r["question"], evidence))
            verdict = judge_answer(judge_client, r["question"], evidence, res["content"])
            res["grounded"] = verdict["grounded"]
            res["violation_type"] = verdict["violation_type"]
            per_model[m].append(res)
            p(f"{m:<18}{r['case_id']:<10}{r['intent']:<12}"
              f"{str(res['first_reasoning_s']):<11}{str(res['first_token_s']):<11}{res['full_s']:<9}"
              f"{str(res['completion_tokens']):<12}{str(res['reasoning_tokens']):<14}"
              f"{res['content_len']:<8}{verdict['grounded']}")

    p("")
    p("=" * 100)
    p("汇总")
    p("=" * 100)
    for m in MODELS:
        rows = per_model[m]
        ft = [r["first_token_s"] for r in rows if r["first_token_s"] is not None]
        full = [r["full_s"] for r in rows]
        rt = [r["reasoning_tokens"] or 0 for r in rows]
        ct = [r["completion_tokens"] or 0 for r in rows]
        judged = [r for r in rows if r["grounded"] is not None]
        grounded = [r for r in judged if r["grounded"]]
        p(f"[{m}]")
        p(f"  首 token（正文）  ：mean={statistics.mean(ft):.2f}s  min={min(ft):.2f}  max={max(ft):.2f}  n={len(ft)}")
        p(f"  首个思考分片      ："
          + ("  ".join(f"{r['first_reasoning_s']}" for r in rows if r['first_reasoning_s']))
          + ("  （无 reasoning_content）" if not any(r['first_reasoning_s'] for r in rows) else ""))
        p(f"  完整回答          ：mean={statistics.mean(full):.2f}s  max={max(full):.2f}")
        p(f"  reasoning_tokens  ：mean={statistics.mean(rt):.0f}  max={max(rt)}  （0 表示无思考过程）")
        p(f"  completion_tokens ：mean={statistics.mean(ct):.0f}  max={max(ct)}")
        p(f"  答案有据率        ：{len(grounded)}/{len(judged)} = "
          f"{(len(grounded) / len(judged) if judged else 0):.1%}（判官失败 {len(rows) - len(judged)} 条剔除）")
    p("=" * 100)

    report = "\n".join(lines)
    print(report)
    OUT.write_text(report + "\n", encoding="utf-8")
    print(f"\n原始输出已写入：{OUT.relative_to(PROJECT_ROOT)}")


main()
