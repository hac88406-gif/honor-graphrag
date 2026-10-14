r"""M3 验收证据脚本：打印 `/api/chat/sync` 在三条关键路径下的真实响应。

与 M2 的 `scripts/verify_data_layer.py` 同属「复跑校验」类脚本：把验收要看的性质
变成可重复执行的命令，避免报告里的结论只能靠人工复述。

三条路径（对应 M3 验收项）：
  A 正常路径（Neo4j 可用）      —— 图谱依据 + 引用条数 + 多意图留痕
  B Neo4j 断开（monkeypatch）    —— 图谱单路意图必须补一次向量检索、答案标注降级、HTTP 200
  C 越界拒答（全程不碰 Neo4j）    —— 意图分流到 reject，HTTP 200 且给出替代提问方向

用法（Neo4j 需在线，供 A 段使用）：
  python scripts/verify_api_smoke.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

logging.disable(logging.CRITICAL)

from app.agent import graph as graph_mod  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory.checkpointer import open_checkpointer  # noqa: E402
from app.retrieval.neo4j_client import GraphUnavailable  # noqa: E402


async def call(client: httpx.AsyncClient, question: str, session_id: str) -> None:
    r = await client.post("/api/chat/sync", json={"session_id": session_id, "question": question})
    body = r.json()
    print(f"\nPOST /api/chat/sync  question={question!r}")
    print(f"  HTTP {r.status_code}")
    print(f"  type={body['type']}  intent={body['intent']}  confidence={body['confidence']}")
    print(f"  entities={[e['canonical_name'] for e in body['entities']]}")
    print(f"  citations={len(body['citations'])}  clarify_options={body['clarify_options']}")
    print(f"  debug.matched_intents={body['debug']['matched_intents']}")
    print(f"  debug.degraded={body['debug']['degraded']}  graph_available={body['debug']['graph_available']}")
    print(f"  answer={body['answer'][:160]!r}")


async def main() -> None:
    # debug 块（matched_intents / degraded / coref_resolved）是排查静默失败的窗口，证据里要看它
    settings.DEBUG = True

    async with open_checkpointer(":memory:") as cp:
        await graph_mod.reset_graph()

        async def _test_checkpointer():
            return cp

        graph_mod.get_checkpointer = _test_checkpointer

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            print("=" * 72)
            print("【A】正常路径（Neo4j 可用）")
            print("=" * 72)
            await call(client, "铠被谁克制", "ev-normal")
            await call(client, "铠的出装和铭文", "ev-multi")

            print("\n" + "=" * 72)
            print("【B】Neo4j 断开（模拟）：图谱单路意图应补一次向量检索")
            print("=" * 72)
            import app.agent.nodes.graph_query as gq

            def _boom(*_args, **_kwargs):
                raise GraphUnavailable("simulated: Neo4j 断开")

            gq.query_evidence = _boom
            await call(client, "铠被谁克制", "ev-degrade")

            print("\n" + "=" * 72)
            print("【C】越界拒答（全程不碰 Neo4j）")
            print("=" * 72)
            await call(client, "今天天气怎么样", "ev-reject")

        await graph_mod.reset_graph()


asyncio.run(main())
