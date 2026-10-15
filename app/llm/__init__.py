"""M4 生成层：云端 LLM 客户端 / prompt 集中维护 / 生成后校验。

三个模块的职责边界（对应规格书 4.9 生成阶段约束的三条要求）：

  - `prompts.py` —— **prompt 集中维护**（4.9 明确要求，禁止散落在节点里）。
    生成约束的「第一条防线」写在这里：只能依据资料回答、不得引入资料外事实。
  - `client.py`   —— 云端客户端。两条实测约束在此收敛成代码：
    ① `reasoning_content` 与正文**严格隔离**（推理模型才有该字段，绝不能当答案返回）；
    ② 调用成功的判定 = **content 非空 AND finish_reason != 'length'**（否则「HTTP 200 + 空答案」会当正常回答往下走）。
  - `guard.py`    —— **生成后校验**。实测证明 prompt 挡不住「把资料里的解释当类别」的越界归纳，
    故必须有第二条防线；guard 不通过一律回落确定性证据组装。

`prompts.py` 与 `guard.py` 都是**纯函数 / 纯常量**，不碰网络，可离线单测；
网络只出现在 `client.py`。
"""
from __future__ import annotations

from app.llm.client import (
    CloudChatClient,
    LLMCallError,
    LLMGenerationError,
    LLMResult,
    LLMUnavailableError,
    get_cloud_client,
)
from app.llm.guard import GuardResult, check_answer
from app.llm.prompts import SYSTEM_GENERATE, build_messages, render_evidence

__all__ = [
    "CloudChatClient",
    "LLMCallError",
    "LLMGenerationError",
    "LLMResult",
    "LLMUnavailableError",
    "get_cloud_client",
    "GuardResult",
    "check_answer",
    "SYSTEM_GENERATE",
    "build_messages",
    "render_evidence",
]
