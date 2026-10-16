"""云端 LLM 不可达 / 未配置时的链路韧性（M4 前置硬要求；M6 更新）。

背景：本机不保证有可用的云端 LLM。项目里触及 LLM 的只有两处：
  1. `/api/health` 的 LLM 探测（`_check_llm`，只回状态，失败不抛）；
  2. 答案生成（云端生成失败一律回落确定性证据组装，见 `app/llm/client.py` 的 fail-fast）。

**意图识别不触及任何 LLM**（确定性关键词规则，见 DECISIONS 2026-10-14 / 2026-10-16）——
`route_llm` 与 Ollama 依赖已在 M6 按数据裁定整体移除。本文件把这两点固化成断言：
任何一次重构若把意图路径改成调 LLM、或让 health 探测抛错，都会在这里失败。
"""
from __future__ import annotations

import httpx
import pytest

from app.api.health import _check_llm
from app.config import settings
from app.retrieval.intent import route


@pytest.fixture
def net_down(monkeypatch):
    """让任何真实网络调用立刻失败（离线、确定性）。"""
    def _boom(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "post", _boom)
    monkeypatch.setattr(httpx, "stream", _boom)


def test_health_llm_probe_reports_unconfigured_without_raising(monkeypatch, net_down):
    """未配置云端 LLM 时只回 `ok=False` + detail，绝不抛异常（配置缺失属预期状态）。"""
    for name in ("CLOUD_BASE_URL", "CLOUD_API_KEY", "CLOUD_CHAT_MODEL"):
        monkeypatch.setattr(settings, name, "")

    out = _check_llm()

    assert out["ok"] is False
    assert "未配置" in out["detail"]


def test_health_llm_probe_reports_unreachable_without_raising(monkeypatch, net_down):
    """已配置但云端不可达：只回 `ok=False` + detail，绝不抛异常。"""
    monkeypatch.setattr(settings, "CLOUD_BASE_URL", "https://127.0.0.1:1/v1")
    monkeypatch.setattr(settings, "CLOUD_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "CLOUD_CHAT_MODEL", "deepseek-v4-pro")

    out = _check_llm()

    assert out["ok"] is False
    assert "LLMUnavailableError" in out["detail"]


def test_intent_route_never_touches_network(net_down):
    """意图路径必须完全离线：任何网络调用被禁用时仍要正常返回。

    若这里失败，说明有人把意图实现改成了调 LLM —— 断网/无 key 时整条链路会断。
    """
    r = route("铠被谁克制")

    assert r.intent == "COUNTER_BY"
    assert r.method == "rule"
