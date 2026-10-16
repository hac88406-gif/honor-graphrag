"""云端 LLM 客户端（规格书 4.9 / 9.1-3「外部调用必须有超时与异常处理」）。

本模块把需求方 2026-10-15 的三条实测发现**收敛成代码契约**：

  1. **模型名以 .env 为准**：`CLOUD_CHAT_MODEL=deepseek-v4-pro`。`GET /models` 只返回
     `['deepseek-flash','deepseek-v4-pro']`，没有 `deepseek-chat`（它仍可调，是兼容别名）。
     故代码里**不得硬编码任何模型名**（9.1-2），一律取 `settings.CLOUD_CHAT_MODEL`。
  2. **`reasoning_content` 与正文严格隔离**：flash 与 v4-pro 都是推理模型，响应里除 `content`
     外还有 `reasoning_content`。本客户端把思考放在 `LLMResult.reasoning` 里**单独返回**，
     正文只取 `content`；流式时 reasoning 分片只用于触发一次「正在思考」提示（见 `on_reasoning`），
     **绝不混入正文**。成本统计用 `completion_tokens`（**含思考**），另用
     `completion_tokens_details.reasoning_tokens` 拆分思考占比。
  3. **空答案的静默失败必须 fail-fast**：实测 `max_tokens=200` 时重问题返回
     **HTTP 200 + `finish_reason='length'` + `content` 为空字符串**。若只看 HTTP 状态码，
     一个「成功」的响应里藏着空答案，会被当成正常回答往下走。
     故成功判定固化为 `LLMResult.is_success`：**`content` 非空 AND `finish_reason != 'length'`**，
     不满足即抛 `LLMGenerationError`，由调用方回落确定性证据组装。

  4. **采样参数必须显式下发**（M6 审核裁定）：此前本客户端**完全不下发 `temperature`**，
     走 API 默认值，随机性高 —— 同一问句 + 同一依据两次跑批答案可差 47/78 条，
     导致评测指标不可复现、人工抽检的判定对象每次都在变。故 `temperature`（默认 0.0，
     取自 `settings.LLM_TEMPERATURE`）**一律随 payload 下发**，并回填进 `LLMResult`
     留痕（`temperature` / `seed`），便于事后核对「这一批是用什么参数跑的」。

错误分两类，因为**处理方式相同但归因不同**（排查时要知道是「拿不到响应」还是「拿到了但不可用」）：
`LLMUnavailableError`（未配置 / 网络 / HTTP 非 200）与 `LLMGenerationError`（HTTP 200 但结果不可用）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMCallError(Exception):
    """LLM 调用类错误的基类。调用方一律回落，不允许穿透到 API 层（9.1-3）。"""


class LLMUnavailableError(LLMCallError):
    """未配置 / 网络失败 / HTTP 非 200 —— 「拿不到响应」。"""


class LLMGenerationError(LLMCallError):
    """HTTP 200 但结果不可用：空答案，或被 max_tokens 截断（finish_reason='length'）。"""


@dataclass(frozen=True)
class LLMResult:
    content: str
    reasoning: str = ""
    finish_reason: str | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    model: str = ""
    # 本次实际下发的采样参数（M6 审核裁定：评测必须确定性，参数必须留痕可查）。
    temperature: float | None = None
    seed: int | None = None

    @property
    def is_success(self) -> bool:
        """调用成功的判定（需求方 2026-10-15 要求固化为断言）：
        **content 非空 AND finish_reason != 'length'**。
        """
        return bool(self.content.strip()) and self.finish_reason != "length"

    def failure_reason(self) -> str:
        """不通过时的原因（写进 state.error / debug，避免「失败了但看不出为什么」）。"""
        if not self.content.strip():
            return f"空答案（finish_reason={self.finish_reason}）"
        if self.finish_reason == "length":
            return f"被 max_tokens 截断（completion_tokens={self.completion_tokens}）"
        return ""


class CloudChatClient:
    """OpenAI 兼容的 chat/completions 客户端（DeepSeek 实测可用）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        max_tokens: int,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        # 采样参数一律显式下发：**不下发 = 走 API 默认值 = 不可复现**（M6 审核根因）。
        self.temperature = temperature
        self.seed = seed

    # ---------------------------------------------------------------- 内部

    def _url(self, path: str = "/chat/completions") -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, messages: list[dict], *, stream: bool, max_tokens: int | None = None) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": stream,
            "temperature": self.temperature,
        }
        # seed 仅在配置了才下发：云端不支持该字段时，多传一个未知参数会被判为非法请求。
        if self.seed is not None:
            payload["seed"] = self.seed
        return payload

    def _finalize(self, result: LLMResult) -> LLMResult:
        """成功判定只有一个出口：不通过即抛，避免调用方漏判（静默失败防御）。"""
        logger.info(
            "云端生成：model=%s temp=%s seed=%s finish=%s completion_tokens=%s reasoning_tokens=%s content_len=%d",
            result.model, result.temperature, result.seed, result.finish_reason,
            result.completion_tokens, result.reasoning_tokens, len(result.content),
        )
        if not result.is_success:
            raise LLMGenerationError(f"生成结果不可用：{result.failure_reason()}")
        return result

    @staticmethod
    def _usage_counts(usage: dict) -> tuple[int | None, int | None]:
        details = usage.get("completion_tokens_details") or {}
        return usage.get("completion_tokens"), details.get("reasoning_tokens")

    # ---------------------------------------------------------------- 非流式

    def chat(self, messages: list[dict], *, max_tokens: int | None = None) -> LLMResult:
        """非流式调用。`max_tokens` 可**按调用覆盖**——评测判官需要更大的思考空间
        （见 config.JUDGE_MAX_TOKENS），生成路径仍用全局 `LLM_MAX_TOKENS`。"""
        try:
            resp = httpx.post(
                self._url(), json=self._payload(messages, stream=False, max_tokens=max_tokens),
                headers=self._headers(), timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"云端请求失败：{type(e).__name__}: {e}") from e

        if resp.status_code != 200:
            raise LLMUnavailableError(f"云端返回 HTTP {resp.status_code}：{resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as e:
            raise LLMUnavailableError(f"云端返回非 JSON：{resp.text[:200]}") from e

        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        completion_tokens, reasoning_tokens = self._usage_counts(body.get("usage") or {})
        return self._finalize(LLMResult(
            content=message.get("content") or "",
            reasoning=message.get("reasoning_content") or "",
            finish_reason=choice.get("finish_reason"),
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            model=body.get("model") or self.model,
            temperature=self.temperature,
            seed=self.seed,
        ))

    # ---------------------------------------------------------------- 流式

    def stream_chat(
        self,
        messages: list[dict],
        *,
        on_reasoning: Callable[[], None] | None = None,
    ) -> LLMResult:
        """流式调用：正文与思考**分开累积**，返回与非流式同构的 `LLMResult`。

        `on_reasoning` 在收到**首个** reasoning 分片时回调一次，供编排层推送
        「正在思考」状态提示（4.9 v1.5：可展示为提示，但不得混入正文）。
        流式同样执行 fail-fast：末尾若 content 为空或 finish_reason='length' 即抛错。
        """
        payload = self._payload(messages, stream=True)
        payload["stream_options"] = {"include_usage": True}   # 让流式也返回 usage（成本统计用）

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason: str | None = None
        usage: dict = {}
        model = self.model
        notified = False

        try:
            with httpx.stream(
                "POST", self._url(), json=payload, headers=self._headers(), timeout=self.timeout,
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise LLMUnavailableError(f"云端返回 HTTP {resp.status_code}：{resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        # 单行坏数据不应中断整段流；但也不静默——记 warning 便于排查
                        logger.warning("流式响应出现无法解析的分片：%r", data[:120])
                        continue
                    model = obj.get("model") or model
                    if obj.get("usage"):
                        usage = obj["usage"]
                    choice = (obj.get("choices") or [{}])[0]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning_parts.append(delta["reasoning_content"])
                        if not notified and on_reasoning is not None:
                            notified = True
                            on_reasoning()
                    if delta.get("content"):
                        content_parts.append(delta["content"])
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"云端流式请求失败：{type(e).__name__}: {e}") from e

        completion_tokens, reasoning_tokens = self._usage_counts(usage)
        return self._finalize(LLMResult(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
            finish_reason=finish_reason,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            model=model,
            temperature=self.temperature,
            seed=self.seed,
        ))

    # ---------------------------------------------------------------- 探测

    def list_models(self) -> list[str]:
        """GET /models（health 探测用）。模型名一律来自配置，此方法只做可用性探测。"""
        try:
            resp = httpx.get(self._url("/models"), headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"云端请求失败：{type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise LLMUnavailableError(f"云端返回 HTTP {resp.status_code}：{resp.text[:200]}")
        return [m.get("id") for m in resp.json().get("data", []) if m.get("id")]


def get_cloud_client() -> CloudChatClient | None:
    """按配置构造客户端；**配置不完整时返回 None**。

    返回 None 是刻意设计：调用方必须把「没配置」当成**生成失败**去回落确定性组装，
    而不是悄悄换一条路（那会让「云端没配」这件事在演示时看不出来）。
    """
    missing = [
        name for name, value in (
            ("CLOUD_BASE_URL", settings.CLOUD_BASE_URL),
            ("CLOUD_API_KEY", settings.CLOUD_API_KEY),
            ("CLOUD_CHAT_MODEL", settings.CLOUD_CHAT_MODEL),
        ) if not value
    ]
    if missing:
        logger.warning("云端 LLM 未配置（缺 %s），生成层将回落确定性证据组装", "、".join(missing))
        return None
    return CloudChatClient(
        base_url=settings.CLOUD_BASE_URL,
        api_key=settings.CLOUD_API_KEY,
        model=settings.CLOUD_CHAT_MODEL,
        timeout=settings.LLM_TIMEOUT,
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=settings.LLM_TEMPERATURE,
        seed=settings.LLM_SEED,
    )
