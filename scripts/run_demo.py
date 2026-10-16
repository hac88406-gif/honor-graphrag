"""M7 演示脚本（规格书 8.1 / 7-M7）——按固定问题清单真实打一遍 /api/chat/sync。

为什么要有这个脚本，而不是「手动在 Postman 里点几下」：
  M7 验收是「陌生人按 README 能在 15 分钟内跑起来」。光有启动步骤不够——跑起来之后
  **打什么、应看到什么**必须可复制，否则复核者只能自己瞎试，也就无法判断「跑对了没有」。
  故把演示清单固化成脚本：同一份清单既能写进 `docs/demo-script.md`，也能一键复跑并落证据。

用法（需先按 README 起 Neo4j + uvicorn，且 .env 里 GENERATION_MODE=llm 走真实生产路径）：
  .\\.venv\\Scripts\\python scripts\\run_demo.py                      # 打到 127.0.0.1:8000
  .\\.venv\\Scripts\\python scripts\\run_demo.py --base-url http://127.0.0.1:8000
  .\\.venv\\Scripts\\python scripts\\run_demo.py --out docs/milestones/M7-demo-output.txt

清单覆盖 8.1 全部八类场景（克制 / 出装铭文 / 搭档 / 打法版本 / 混合对位 / 多轮追问 / 拒答越界 / 实体异常），
每类取 1~2 条代表问句，多轮链单独跑一条两轮链。**问句与期望值取自 `tests/eval/cases.yaml`**（同一份标注，
避免演示清单与评测集两套口径）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 演示清单：每项 = 一条用例（多轮用 turns 表达），期望值取自 tests/eval/cases.yaml 的人工标注
DEMO: list[dict] = [
    {"id": "G-01", "category": "图谱-克制/被克制", "turns": ["铠被谁克制"],
     "expect": "COUNTER_BY / answer", "note": "图谱入边：谁克制铠"},
    {"id": "G-05", "category": "图谱-克制/被克制", "turns": ["貂蝉克制谁"],
     "expect": "COUNTER_OF / answer", "note": "图谱出边：貂蝉克制谁（方向与上一条相反）"},
    {"id": "B-02", "category": "图谱-出装", "turns": ["亚瑟怎么出装"],
     "expect": "ITEM_BUILD / answer", "note": "图谱：官方两套推荐出装"},
    {"id": "B-03", "category": "图谱-铭文", "turns": ["貂蝉的铭文怎么搭配"],
     "expect": "INSCRIPTION / answer", "note": "多意图留痕：『搭配』还会命中 SYNERGY"},
    {"id": "S-01", "category": "图谱-搭档", "turns": ["谁和鲁班七号配合好"],
     "expect": "SYNERGY / answer", "note": "图谱：官方推荐搭档（无向关系）"},
    {"id": "T-01", "category": "文本-打法", "turns": ["貂蝉对线思路"],
     "expect": "GAMEPLAY / answer", "note": "向量：C1 官方技能/打法文本"},
    {"id": "T-07", "category": "文本-版本", "turns": ["这个版本谁强"],
     "expect": "TIER_META / low_confidence", "note": "无英雄槽位：只按 patch 窗口过滤，弱证据降级"},
    {"id": "H-01", "category": "混合-对位", "turns": ["我玩铠怎么打吕布"],
     "expect": "MATCHUP / answer", "note": "图谱引导向量：槽位含我方+敌方"},
    {"id": "H-04", "category": "混合-对位", "turns": ["怎么打东皇太一"],
     "expect": "MATCHUP / clarify", "note": "只给敌方、缺我方 -> 槽位不完整 -> 澄清反问（不是拒答）"},
    {"id": "M-01", "category": "多轮追问", "turns": ["铠被谁克制", "那铭文呢"],
     "expect": "第1轮 COUNTER_BY/answer -> 第2轮 INSCRIPTION/answer（继承『铠』）",
     "note": "纯指代『那铭文呢』靠上一轮实体消解，同一 session_id"},
    {"id": "R-01", "category": "拒答-越界", "turns": ["今天天气怎么样"],
     "expect": "OUT_OF_SCOPE / reject", "note": "话题越界：不属于王者问答域"},
    {"id": "R-05", "category": "拒答-知识库未收录", "turns": ["铭文怎么分解"],
     "expect": "INSCRIPTION / reject", "note": "命中封闭意图但图谱 0 条 + 向量无据 -> 拒答"},
    {"id": "E-01", "category": "实体异常", "turns": ["凯被谁克制"],
     "expect": "COUNTER_BY / answer", "note": "同音错别字『凯』-> 拼音模糊链接到『铠』"},
    {"id": "E-03", "category": "实体异常", "turns": ["猴子怕谁"],
     "expect": "COUNTER_BY / answer", "note": "纯昵称『猴子』-> 别名表链接到『孙悟空』"},
]


def _fmt_entities(resp: dict) -> str:
    """实体链接结果：原文 -> 规范名(id)，带链接方式（exact/alias/fuzzy/none）。

    method 要打出来：实体异常那两条用例的价值全在「『凯』是靠 fuzzy 而非 exact 链接上的」，
    只给规范名看不出这一层。
    """
    ents = resp.get("entities") or []
    if not ents:
        return "（无）"
    return " / ".join(
        f"{e.get('raw')}->{e.get('canonical_name')}({e.get('canonical_id')},{e.get('method')})"
        for e in ents
    )


def _fmt_citations(resp: dict) -> str:
    cits = resp.get("citations") or []
    if not cits:
        return "（无来源卡片）"
    return "; ".join(f"【{c['index']}】{c['label']}" for c in cits)


def _run_turn(client: httpx.Client, base_url: str, session_id: str, question: str) -> dict:
    t0 = time.perf_counter()
    r = client.post(f"{base_url}/api/chat/sync",
                    json={"session_id": session_id, "question": question}, timeout=120.0)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    resp = r.json()
    resp["_elapsed"] = elapsed
    return resp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="docs/milestones/M7-demo-output.txt")
    args = ap.parse_args()

    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("=" * 78)
    emit("M7 演示脚本实跑输出（规格书 8.1 八类场景；真实 HTTP 打 /api/chat/sync）")
    emit(f"base_url = {args.base_url}　时间 = {time.strftime('%Y-%m-%d %H:%M:%S')}")
    emit("=" * 78)

    # 健康检查先跑：三项组件必须全绿，否则后面所有结果都不可信（fail-fast，不掩盖）
    # trust_env=False：本机可能配了 HTTP(S)_PROXY，而演示打的是 127.0.0.1 —— 走代理会连不上本地服务
    with httpx.Client(trust_env=False) as client:
        try:
            h = client.get(f"{args.base_url}/api/health", timeout=15.0).json()
        except Exception as e:  # noqa: BLE001 - 演示脚本，直接报错退出即可
            print(f"[FATAL] /api/health 不可达：{e}\n请先按 README 起 Neo4j 与 uvicorn。")
            return 2
        emit(f"[health] neo4j={h['neo4j']['ok']}  chroma={h['chroma']['ok']}  llm={h['llm']['ok']}")
        emit(f"         llm detail: {h['llm']['detail']}")
        if not all(h[k]["ok"] for k in ("neo4j", "chroma", "llm")):
            emit("[WARN] 有组件不 ok，下面的结果需按降级路径解读。")
        emit("")

        n_turn = 0
        for case in DEMO:
            sid = f"demo-{case['id']}"   # 每条用例独立 session（多轮链共用同一个 sid）
            for i, q in enumerate(case["turns"], start=1):
                n_turn += 1
                resp = _run_turn(client, args.base_url, sid, q)
                dbg = resp.get("debug") or {}
                ev = dbg.get("evidence") or []
                n_graph = sum(1 for e in ev if e.get("kind") == "graph")
                n_vec = sum(1 for e in ev if e.get("kind") == "vector")
                tag = f"[{n_turn:02d}] {case['category']}"
                if len(case["turns"]) > 1:
                    tag += f"（第 {i}/{len(case['turns'])} 轮）"
                emit("─" * 78)
                emit(f"{tag}　{case['id']}")
                emit(f"  问句　　：{q}")
                emit(f"  期望　　：{case['expect']}")
                emit(f"  实际　　：intent={resp['intent']}  type={resp['type']}  "
                     f"conf={resp['confidence']:.3f}  matched={dbg.get('matched_intents')}")
                emit(f"  实体　　：{_fmt_entities(resp)}")
                emit(f"  依据　　：图谱 {n_graph} 条 / 向量 {n_vec} 条（共 {len(ev)}）  "
                     f"degraded={dbg.get('degraded')}")
                if dbg.get("coref_resolved"):
                    emit(f"  指代消解：{dbg.get('coref_resolved')}  ->  {dbg.get('resolved_question')}")
                emit(f"  耗时　　：{resp['_elapsed']:.2f}s")
                emit(f"  答案　　：{resp['answer']}")
                if resp.get("clarify_options"):
                    emit(f"  澄清候选：{resp['clarify_options']}")
                emit(f"  来源　　：{_fmt_citations(resp)}")
                emit(f"  说明　　：{case['note']}")
            emit("")

    emit("=" * 78)
    emit(f"共 {n_turn} 个 turn 跑完（真实 HTTP 调用，非桩数据）。")
    emit("=" * 78)

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[out] 已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
