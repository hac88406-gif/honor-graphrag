"""Ollama 不可达时的链路韧性（M4 前置硬要求，需求方 2026-10-15）。

背景：需求方实测本机 Ollama 未运行（`11434` 连接被拒）。本项目 `LLM_MODE=hybrid`
下**意图默认走确定性规则**（`route(use_llm=False)`，见 DECISIONS 2026-10-14）、
生成走云端，Ollama 只在两条路径上被触及：

  1. `/api/health` 的 LLM 探测（`_check_llm`，只回状态，失败不抛）；
  2. 可选增强 `route_llm`（仅 `use_llm=True` 时调用，且整体包在 try/except 里回落规则）。

本文件把「Ollama 不可达不报错」固化成断言。**为什么值得单独一个文件**：Ollama 是
一条**可选**路径，可选路径最容易在某次重构里被改成默认路径，于是本机没起 Ollama 的
演示环境直接 500 —— 正是本项目一贯在防的「依赖缺失导致链路断」的静默失败。
"""
from __future__ import annotations

import httpx
import pytest

from app.api.health import _check_llm
from app.config import settings
from app.retrieval.intent import route


@pytest.fixture
def ollama_down(monkeypatch):
    """把 Ollama 打成「连接被拒」，并让任何真实网络调用立刻失败（离线、确定性）。"""
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:1")

    def _boom(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "post", _boom)


def test_health_llm_probe_reports_down_without_raising(ollama_down):
    """`/api/health` 的 LLM 探测：不可达只回 `ok=False` + detail，绝不抛异常。"""
    out = _check_llm()

    assert out["ok"] is False
    assert "ConnectError" in out["detail"]


def test_default_intent_route_never_touches_ollama(ollama_down):
    """默认意图路径（`use_llm=False`）不得发起任何 Ollama 请求。

    若这里失败，说明有人把意图默认实现改成了调 Ollama —— 本机没起 Ollama 时整条链路会断。
    """
    r = route("铠被谁克制")

    assert r.intent == "COUNTER_BY"
    assert r.method == "rule"


def test_route_llm_unreachable_falls_back_to_rules(ollama_down):
    """显式开启 LLM 意图路径时，Ollama 不可达也必须回落规则路径（不得抛错穿透）。"""
    r = route("铠被谁克制", use_llm=True)

    assert r.method == "rule"
    assert r.intent == "COUNTER_BY"
