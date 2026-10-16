"""M6 可复现性实测 —— temperature=0 下「同问句 + 同依据」连跑 N 次是否**逐字一致**
（需求方 2026-10-16 审核 · 第二层）。

**为什么需要这个脚本**：根因是 LLM 客户端此前**完全不下发 temperature**（走 API 默认值），
随机性高 —— 实测同一问句 + 同一依据两次跑批答案可差 47/78 条，导致「答案有据率」的判分
对象每次都在变、人工抽检臂的 39 条判定无法复用。修完 `LLM_TEMPERATURE=0.0` 之后，
必须**实测确认真的确定**，否则「可复现」只是口头声明。

做法：
  - 取**真实问句 + 真实依据**（从 `docs/milestones/M6-eval-raw.json` 里捞，覆盖不同意图），
    prompt 走**生产路径**（`app.llm.build_messages`），不另造输入；
  - 同一输入**连跑 N 次**，逐字比对 `content`；
  - 另探测云端是否支持 `seed`（多传该字段是否被判非法）。

判定（对应需求方要求）：
  - 全组逐字一致 → 确定性达标，**可单次跑批报数**；
  - 存在不一致（推理模型可能有内置非确定性）→ **不得硬报单次数字**，
    改为多次采样报均值与区间（见 M6 报告）。

用法：
    python scripts/measure_determinism.py [--runs 3] [--samples 5]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.llm import build_messages, get_cloud_client  # noqa: E402
from app.llm.client import CloudChatClient, LLMCallError  # noqa: E402
from app.schemas.chat import Evidence  # noqa: E402

RAW = ROOT / "docs" / "milestones" / "M6-eval-raw.json"
OUT = ROOT / "docs" / "milestones" / "M6-determinism-output.txt"

_EVIDENCE_FIELDS = ("kind", "content", "relation", "score", "source", "patch", "hero_ids")


def _to_evidence(raw_items: list[dict]) -> list[Evidence]:
    """把落盘的 evidence dict 还原成 `Evidence` 对象（字段与落盘结构一一对应）。"""
    out: list[Evidence] = []
    for it in raw_items:
        kwargs = {k: it.get(k) for k in _EVIDENCE_FIELDS}
        out.append(Evidence(**kwargs))
    return out


def _pick_samples(records: list[dict], limit: int) -> list[dict]:
    """按意图去重挑样本：只取「有依据且走过生成」的 turn，保证 prompt 有料可比。"""
    picked: list[dict] = []
    seen: set[str] = set()
    for r in records:
        if r.get("type") not in ("answer", "low_confidence"):
            continue
        if not r.get("evidence"):
            continue
        key = r.get("intent") or "?"
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= limit:
            break
    return picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="同一输入重复次数（需求方要求 3）")
    ap.add_argument("--samples", type=int, default=5, help="抽样组数（覆盖不同意图）")
    args = ap.parse_args()

    raw = json.loads(RAW.read_text(encoding="utf-8"))
    samples = _pick_samples(raw["records"], args.samples)

    lines: list[str] = []

    def p(s: str = "") -> None:
        print(s)
        lines.append(s)

    p("=" * 78)
    p("M6 可复现性实测 —— temperature=0 下「同问句 + 同依据」连跑 N 次是否逐字一致")
    p("（需求方 2026-10-16 审核 · 第二层）")
    p("=" * 78)
    p(f"采样来源：{RAW.relative_to(ROOT)}（真实问句 + 真实依据；prompt 走生产路径 build_messages）")
    p(f"下发参数：temperature={settings.LLM_TEMPERATURE}（settings.LLM_TEMPERATURE）  "
      f"seed={settings.LLM_SEED}（settings.LLM_SEED）")
    p(f"运行次数：{args.runs}    抽样组数：{len(samples)}")
    p("")

    client = get_cloud_client()
    if client is None:
        p("**云端 LLM 未配置**（缺 CLOUD_BASE_URL / CLOUD_API_KEY / CLOUD_CHAT_MODEL），无法实测。")
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    p(f"客户端：model={client.model}  temperature={client.temperature}  seed={client.seed}")
    p("")

    # ---- seed 支持探测（多传未知参数是否被判非法） ----
    seed_probe = CloudChatClient(
        base_url=settings.CLOUD_BASE_URL, api_key=settings.CLOUD_API_KEY,
        model=settings.CLOUD_CHAT_MODEL, timeout=settings.LLM_TIMEOUT,
        max_tokens=settings.LLM_MAX_TOKENS, temperature=0.0, seed=42,
    )
    seed_ok = True
    try:
        seed_probe.chat(build_messages("铠被谁克制", _to_evidence(samples[0].get("evidence") or [])))
    except LLMCallError as e:
        seed_ok = False
        p(f"seed 探测：云端**拒绝** seed（{type(e).__name__}: {e}）→ 只能靠 temperature=0。")
    else:
        p("seed 探测：云端**接受** seed → 下面追加「固定 seed」一轮对照。")
    p("")

    def run_phase(label: str, probe_client: CloudChatClient) -> int:
        """跑一轮：每组同一输入连跑 N 次，返回逐字一致的组数。"""
        p("=" * 78)
        p(f"【{label}】temperature={probe_client.temperature}  seed={probe_client.seed}")
        p("=" * 78)
        identical = 0
        for i, r in enumerate(samples, 1):
            question = r.get("resolved_question") or r.get("question") or ""
            evidence = _to_evidence(r.get("evidence") or [])
            messages = build_messages(question, evidence)
            p(f"[{i}/{len(samples)}] {r['case_id']} {r.get('intent')}  问句={question}  依据 {len(evidence)} 条")
            contents: list[str] = []
            err: str | None = None
            for _ in range(args.runs):
                try:
                    contents.append(probe_client.chat(messages).content)
                except LLMCallError as e:
                    err = f"{type(e).__name__}: {e}"
                    break
            if err is not None:
                p(f"      调用失败：{err}")
                p("")
                continue
            same = len(set(contents)) == 1
            p(f"      各次正文长度：{[len(c) for c in contents]}")
            p(f"      逐字一致：{'✓ 是' if same else '✗ 否 —— 存在非确定性'}")
            if same:
                identical += 1
                p(f"      正文：{contents[0][:100]!r}")
            else:
                for k, c in enumerate(contents, 1):
                    p(f"      run{k}：{c[:100]!r}")
            p("")
        p(f"  → 小结：{identical}/{len(samples)} 组逐字一致")
        p("")
        return identical

    base_identical = run_phase("A·仅 temperature=0（seed 不固定）", client)

    seed_identical = None
    if seed_ok:
        seed_identical = run_phase("B·temperature=0 + 固定 seed=42", seed_probe)

    p("=" * 78)
    p("结论")
    p("=" * 78)
    p(f"A·temperature=0（不固定 seed）：{base_identical}/{len(samples)} 组逐字一致")
    if seed_identical is not None:
        p(f"B·temperature=0 + seed=42：{seed_identical}/{len(samples)} 组逐字一致")
    if seed_identical == len(samples):
        p("      → **固定 seed 后确定性达标**，可单次跑批报数（把 LLM_SEED 写进 .env 即固化）。")
    elif base_identical == len(samples):
        p("      → **temperature=0 即达标**，可单次跑批报数。")
    else:
        p("      → **未达标**（推理模型存在内置非确定性，与 seed/temperature 无关）：")
        p("         ① 不得硬报单次数字，改为多次采样报均值与区间；**且**")
        p("         ② 按第三层固化答案集（golden set），后续判定一律基于同一份固定答案。")
    p("")
    p(f"输出文件：{OUT.relative_to(ROOT)}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
