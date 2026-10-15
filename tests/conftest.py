"""pytest 全局配置 + 服务依赖门禁（规格书 11.3 v1.5）。

两件事：

1. 把项目根与 `scripts/` 加入 `sys.path`（测试直接 import `scripts/` 下的脚本模块）。
2. 提供服务依赖门禁：`require_neo4j` / `require_chroma` 两个 **session 级**夹具。

**11.3 v1.5 的 fail-fast 要求**：Neo4j / Chroma 依赖的用例，在**验收模式**
（环境变量 `REQUIRE_SERVICES=1`）下服务不可达必须 **fail 而不是 skip**。
理由：M3 实测发现 Neo4j 不可用时 9 个「方向性动态断言」会**静默 skip**，
于是没有 Neo4j 的机器上跑出的 "171 passed" 是**假绿**——防静默方向错误的核心保护根本没执行。

实现要点：
- 门禁函数由夹具**返回**、在**用例体内**调用，因此 `pytest.fail` 计为 `failed`（而非 fixture 的 `error`）；
- 可达性探测在 session 级夹具内**只做一次**，避免每个用例各重试一遍连接（实测 9 个用例白等约 90 秒）；
- 开发时不设 `REQUIRE_SERVICES`，保持 skip 以便快速跑单测。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


# 验收模式开关：True 时服务不可达 -> fail（不是 skip）
REQUIRE_SERVICES = _truthy(os.getenv("REQUIRE_SERVICES"))


def _gate(ok: bool, what: str, detail: str) -> None:
    if ok:
        return
    msg = f"{what} 不可达（{detail}）"
    if REQUIRE_SERVICES:
        pytest.fail(
            f"{msg}：验收模式（REQUIRE_SERVICES=1）下服务依赖用例必须执行，不允许 skip。"
            "请恢复服务后重跑（Neo4j 起 honor-neo4j 容器；Chroma 先跑 scripts/init_chroma.py）。"
        )
    pytest.skip(f"{msg}：跳过（开发模式；验收请设 REQUIRE_SERVICES=1）")


@pytest.fixture(scope="session")
def require_neo4j():
    """Neo4j 门禁：可达性在本夹具内只探测一次，返回的函数在用例体内调用。"""
    from app.config import settings
    from app.retrieval import neo4j_client

    ok = neo4j_client.health()

    def _check() -> None:
        _gate(ok, "Neo4j", settings.NEO4J_URI)

    return _check


@pytest.fixture(scope="session")
def require_chroma():
    """Chroma 门禁：以 `guides` collection 是否存在为判据。

    只列 collection 名、不加载 1.2GB 的 bge EF，探测成本极低。
    """
    from app.utils.chroma import COLLECTION_NAME, get_client

    try:
        ok = COLLECTION_NAME in [c.name for c in get_client().list_collections()]
    except Exception:  # noqa: BLE001 - 探测失败即视为不可用
        ok = False

    def _check() -> None:
        _gate(ok, "Chroma", f"collection '{COLLECTION_NAME}' 未建立，请先运行 scripts/init_chroma.py")

    return _check


# ---------------------------------------------------------------- 生成层（M4）

@pytest.fixture(autouse=True, scope="session")
def _pin_generation_mode():
    """把答案生成方式钉在 `template`（确定性证据组装）。

    理由：本地 `.env` 若切到 `llm`，跑测试会**真的打云端** —— 变慢、依赖网络、结果不确定，
    与 M3 那些「离线、确定性、可复现」的用例冲突。M4 的生成层用例自行
    `monkeypatch` 成 `llm` 并注入假客户端（见 `fake_cloud`），不依赖真实 key。
    """
    from app.config import settings

    original = settings.GENERATION_MODE
    settings.GENERATION_MODE = "template"
    yield
    settings.GENERATION_MODE = original


class FakeCloudClient:
    """假云端客户端：按脚本产出 `LLMResult`（或抛错），让生成层测试完全离线。

    与 `CloudChatClient` 同构（`chat` / `stream_chat`），因此测的是**真实的**节点与编排代码，
    只是把网络那一层换成了可控输入 —— 不需要 key，也不会产生费用。
    """

    def __init__(
        self,
        *,
        content: str = "",
        reasoning: str = "",
        finish_reason: str | None = "stop",
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        error: Exception | None = None,
    ) -> None:
        from app.llm.client import LLMResult

        self._result = LLMResult(
            content=content,
            reasoning=reasoning,
            finish_reason=finish_reason,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            model="fake-model",
        )
        self.error = error
        self.calls: list[tuple[str, list[dict]]] = []
        self.reasoning_callbacks = 0

    def chat(self, messages: list[dict]):
        self.calls.append(("chat", messages))
        if self.error:
            raise self.error
        return self._result

    def stream_chat(self, messages: list[dict], *, on_reasoning=None):
        self.calls.append(("stream", messages))
        if self.error:
            raise self.error
        # 真实客户端在收到首个 reasoning 分片时回调一次，此处如实模拟（否则测不到「正在思考」）
        if self._result.reasoning and on_reasoning is not None:
            self.reasoning_callbacks += 1
            on_reasoning()
        return self._result

    def list_models(self) -> list[str]:
        return ["fake-model"]


@pytest.fixture
def fake_cloud(monkeypatch):
    """把 `generate` 节点用的客户端换成假客户端，并把生成方式切到 llm。

    返回一个 `install(**kwargs)`：kwargs 直接透传给 `FakeCloudClient`。
    """
    from app.config import settings

    def _install(**kwargs) -> FakeCloudClient:
        client = FakeCloudClient(**kwargs)
        monkeypatch.setattr("app.agent.nodes.generate.get_cloud_client", lambda: client)
        monkeypatch.setattr(settings, "GENERATION_MODE", "llm")
        return client

    return _install
