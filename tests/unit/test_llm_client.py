"""云端 LLM 客户端单测（规格书 4.9 / 9.1-3）。

三条实测发现固化为断言（需求方 2026-10-15）：

  1. **成功判定 = `content` 非空 AND `finish_reason != 'length'`**
     —— 实测 `max_tokens=200` 时重问题返回 `HTTP 200 + finish_reason='length' + content=''`，
     只看 HTTP 状态码会把空答案当正常回答往下走；
  2. **`reasoning_content` 与正文严格隔离** —— 推理模型的思考绝不能出现在 `content` 里，
     且成本统计用 `completion_tokens`（含思考），思考量可从 `reasoning_tokens` 拆出；
  3. **模型名一律来自配置** —— `GET /models` 不含 `deepseek-chat`（兼容别名），代码不得硬编码模型名。

网络层用 monkeypatch 替换（`httpx.post` / `httpx.stream`），全部离线可跑、无费用。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import settings
from app.llm.client import (
    CloudChatClient,
    LLMGenerationError,
    LLMResult,
    LLMUnavailableError,
    get_cloud_client,
)


# ---------------------------------------------------------------- 假 HTTP 层

class _Resp:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _StreamResp:
    """`httpx.stream(...)` 的上下文管理器替身，按行吐出 SSE。"""

    def __init__(self, lines: list[str], *, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self._lines = lines
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> str:
        return self.text


def _client(**kwargs) -> CloudChatClient:
    base = dict(base_url="https://api.example.com", api_key="k", model="m", timeout=5.0, max_tokens=2048)
    base.update(kwargs)
    return CloudChatClient(**base)


def _chat_body(*, content: str, reasoning: str = "", finish: str = "stop", usage: dict | None = None) -> dict:
    return {
        "model": "m",
        "choices": [{
            "message": {"content": content, "reasoning_content": reasoning},
            "finish_reason": finish,
        }],
        "usage": usage or {},
    }


def _sse(delta: dict, *, finish: str | None = None, usage: dict | None = None) -> str:
    obj: dict = {"choices": [{"delta": delta, "finish_reason": finish}]}
    if usage is not None:
        obj["usage"] = usage
    return "data: " + json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- is_success

@pytest.mark.parametrize(
    "content,finish,expected",
    [
        ("有答案", "stop", True),
        ("有答案", "length", False),      # 被 max_tokens 截断 -> 不可用
        ("", "stop", False),              # 空答案
        ("", "length", False),            # 实测的「HTTP 200 + 空答案」形态
        ("   \n ", "stop", False),        # 只有空白也算空
        ("有答案", None, True),           # 流式末尾缺失 finish_reason 时不误判
    ],
)
def test_is_success_rule(content, finish, expected):
    assert LLMResult(content=content, finish_reason=finish).is_success is expected


# ---------------------------------------------------------------- 非流式

def test_chat_success_separates_reasoning_from_content(monkeypatch):
    """正文与思考**分开返回**：思考绝不进 content。"""
    body = _chat_body(
        content="克制铠的英雄是兰陵王。",
        reasoning="先看资料，资料里写的是……",
        usage={"completion_tokens": 253, "completion_tokens_details": {"reasoning_tokens": 200}},
    )
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(payload=body))

    result = _client().chat([{"role": "user", "content": "x"}])

    assert result.content == "克制铠的英雄是兰陵王。"
    assert "资料里写的是" in result.reasoning
    assert "资料里写的是" not in result.content
    # 成本口径：completion_tokens 含思考；思考量单独可拆
    assert result.completion_tokens == 253
    assert result.reasoning_tokens == 200


def test_chat_empty_answer_raises_generation_error(monkeypatch):
    """实测原案：HTTP 200 + finish_reason=length + content 空 -> 必须抛错，不得当正常回答。"""
    body = _chat_body(content="", finish="length", usage={"completion_tokens": 200})
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(payload=body))

    with pytest.raises(LLMGenerationError) as e:
        _client().chat([{"role": "user", "content": "x"}])
    assert "空答案" in str(e.value) or "截断" in str(e.value)


def test_chat_truncated_nonempty_answer_raises(monkeypatch):
    """非空但被截断（finish_reason=length）同样不可用：答案被砍掉一半比空答案更隐蔽。"""
    body = _chat_body(content="克制铠的英雄有兰陵", finish="length")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(payload=body))

    with pytest.raises(LLMGenerationError):
        _client().chat([{"role": "user", "content": "x"}])


def test_chat_http_error_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(status_code=401, text="unauthorized"))
    with pytest.raises(LLMUnavailableError):
        _client().chat([{"role": "user", "content": "x"}])


def test_chat_network_error_raises_unavailable(monkeypatch):
    def _boom(url, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _boom)
    with pytest.raises(LLMUnavailableError):
        _client().chat([{"role": "user", "content": "x"}])


def test_chat_non_json_body_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(text="<html>502</html>"))
    with pytest.raises(LLMUnavailableError):
        _client().chat([{"role": "user", "content": "x"}])


def test_chat_sends_configured_model_and_max_tokens(monkeypatch):
    """模型名与 max_tokens 一律取自配置，不得硬编码（9.1-2）。"""
    seen: dict = {}

    def _post(url, **kwargs):
        seen.update(kwargs["json"])
        return _Resp(payload=_chat_body(content="ok"))

    monkeypatch.setattr(httpx, "post", _post)
    _client(model="deepseek-v4-pro", max_tokens=2048).chat([{"role": "user", "content": "x"}])

    assert seen["model"] == "deepseek-v4-pro"
    assert seen["max_tokens"] == 2048
    assert seen["stream"] is False


def test_chat_max_tokens_can_be_overridden_per_call(monkeypatch):
    """`max_tokens` 可按调用覆盖，且**默认仍取配置值**。

    为什么必须钉住：评测判官要「先读完资料再逐条比对」，资料越长思考越长 ——
    实测沿用生成的 2048 时，5/78 条判官返回空答案（finish_reason=length），
    答案有据率的分母被迫缩小。若后人重构掉这个覆盖参数，该问题会**静默复发**
    （判官失败被计成 judge_error 而不是报错，指标只是分母变小，看不出异常）。
    """
    seen: dict = {}

    def _post(url, **kwargs):
        seen.update(kwargs["json"])
        return _Resp(payload=_chat_body(content="ok"))

    monkeypatch.setattr(httpx, "post", _post)
    c = _client(model="deepseek-v4-pro", max_tokens=2048)

    c.chat([{"role": "user", "content": "x"}], max_tokens=4096)
    assert seen["max_tokens"] == 4096          # 覆盖生效

    c.chat([{"role": "user", "content": "x"}])
    assert seen["max_tokens"] == 2048          # 不传时回落配置值


# ---------------------------------------------------------------- 流式

def _install_stream(monkeypatch, lines: list[str]):
    monkeypatch.setattr(httpx, "stream", lambda method, url, **kw: _StreamResp(lines))


def test_stream_chat_accumulates_content_and_reasoning_separately(monkeypatch):
    _install_stream(monkeypatch, [
        _sse({"reasoning_content": "思考一"}),
        _sse({"reasoning_content": "思考二"}),
        _sse({"content": "克制"}),
        _sse({"content": "铠的是兰陵王。"}),
        _sse({}, finish="stop", usage={"completion_tokens": 300,
                                      "completion_tokens_details": {"reasoning_tokens": 260}}),
        "data: [DONE]",
    ])

    seen = {"n": 0}
    result = _client().stream_chat(
        [{"role": "user", "content": "x"}], on_reasoning=lambda: seen.__setitem__("n", seen["n"] + 1)
    )

    assert result.content == "克制铠的是兰陵王。"
    assert result.reasoning == "思考一思考二"
    assert result.finish_reason == "stop"
    assert result.completion_tokens == 300
    assert result.reasoning_tokens == 260
    assert seen["n"] == 1, "思考提示只在首个 reasoning 分片回调一次"


def test_stream_chat_reasoning_only_is_empty_answer_error(monkeypatch):
    """流式同样 fail-fast：只有思考、没有正文 + finish_reason=length -> 抛错。"""
    _install_stream(monkeypatch, [
        _sse({"reasoning_content": "一直在想"}),
        _sse({}, finish="length", usage={"completion_tokens": 2048}),
        "data: [DONE]",
    ])

    with pytest.raises(LLMGenerationError):
        _client().stream_chat([{"role": "user", "content": "x"}])


def test_stream_chat_tolerates_broken_line(monkeypatch):
    """单行坏数据不中断整段流（否则一次传输抖动就丢掉整个回答）。"""
    _install_stream(monkeypatch, [
        "data: {不是合法 JSON",
        _sse({"content": "答案"}),
        _sse({}, finish="stop"),
        "data: [DONE]",
    ])

    assert _client().stream_chat([{"role": "user", "content": "x"}]).content == "答案"


def test_stream_chat_http_error_raises_unavailable(monkeypatch):
    _install_stream(monkeypatch, [])
    monkeypatch.setattr(httpx, "stream", lambda method, url, **kw: _StreamResp([], status_code=429, text="rate limited"))
    with pytest.raises(LLMUnavailableError):
        _client().stream_chat([{"role": "user", "content": "x"}])


# ---------------------------------------------------------------- 构造

def test_get_cloud_client_returns_none_when_unconfigured(monkeypatch):
    """配置不完整 -> 返回 None，调用方必须按「生成失败」回落（不得悄悄换路径）。"""
    monkeypatch.setattr(settings, "CLOUD_BASE_URL", "")
    monkeypatch.setattr(settings, "CLOUD_API_KEY", "")
    monkeypatch.setattr(settings, "CLOUD_CHAT_MODEL", "")
    assert get_cloud_client() is None


def test_get_cloud_client_uses_settings(monkeypatch):
    monkeypatch.setattr(settings, "CLOUD_BASE_URL", "https://api.deepseek.com/")
    monkeypatch.setattr(settings, "CLOUD_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "CLOUD_CHAT_MODEL", "deepseek-v4-pro")
    monkeypatch.setattr(settings, "LLM_MAX_TOKENS", 2048)

    client = get_cloud_client()
    assert client is not None
    assert client.base_url == "https://api.deepseek.com"   # 末尾斜杠被规范化
    assert client.model == "deepseek-v4-pro"
    assert client.max_tokens == 2048
