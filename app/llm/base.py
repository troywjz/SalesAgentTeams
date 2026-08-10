from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMCallAttempt:
    """单次模型供应商调用尝试，用于追踪 fallback 前后的完整链路。"""

    provider: str
    model: str
    api_url: str
    protocol: str
    attempt_index: int
    success: bool
    elapsed_ms: int
    request_json: dict[str, Any] = field(default_factory=dict)
    response_json: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    call_attempts: list[LLMCallAttempt] = field(default_factory=list)


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: str | None = None,
    ) -> LLMResponse:
        ...


class LLMConfigurationError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        call_attempts: list[LLMCallAttempt] | None = None,
    ) -> None:
        super().__init__(message)
        self.call_attempts = call_attempts or []


class ReasoningTokenLimitExceeded(LLMProviderError):
    """推理模型把 token 预算全部消耗在 reasoning 上，无可见输出。

    通常是 ``finish_reason=length`` 且响应只含 reasoning_content 的场景。
    由 FallbackLLMClient 识别并触发同供应商放宽 max_tokens 后重试一次。
    """

    def __init__(
        self,
        message: str,
        *,
        finish_reason: str = "",
        has_reasoning: bool = False,
    ) -> None:
        super().__init__(message)
        self.finish_reason = finish_reason
        self.has_reasoning = has_reasoning
