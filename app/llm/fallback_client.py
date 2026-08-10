import time
from typing import Any

from app.llm.base import (
    ChatMessage,
    LLMCallAttempt,
    LLMClient,
    LLMProviderError,
    LLMResponse,
    ReasoningTokenLimitExceeded,
)
from app.llm.http_client import HttpLLMClient
from app.llm.providers import LLMProviderConfig
from app.utils.json_tools import extract_json_object


class FallbackLLMClient:
    def __init__(
        self,
        configs: list[LLMProviderConfig],
        *,
        max_attempts: int | None = None,
    ) -> None:
        self.configs = configs
        self.clients: list[LLMClient] = [HttpLLMClient(config) for config in configs]
        self.max_attempts = max_attempts if max_attempts and max_attempts > 0 else None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: str | None = None,
    ) -> LLMResponse:
        if not self.clients:
            raise LLMProviderError("No configured LLM providers or models available.")

        failures: list[str] = []
        call_attempts: list[LLMCallAttempt] = []
        attempts = list(zip(self.configs, self.clients, strict=True))
        if self.max_attempts is not None:
            attempts = attempts[: self.max_attempts]

        # 每个供应商配置最多做一次"放宽 max_tokens"重试，用于推理模型把预算
        # 全部消耗在 reasoning 上、无可见输出的场景；其余异常直接跳过。
        retried = [False] * len(attempts)
        attempt_index = 0
        index = 0
        while index < len(attempts):
            config, client = attempts[index]
            current_max_tokens = (
                _relaxed_max_tokens(max_tokens, config) if retried[index] else max_tokens
            )
            attempt_index += 1
            current_request_json = _request_json(
                messages,
                temperature=temperature,
                max_tokens=current_max_tokens,
                response_format=response_format,
            )
            started = time.perf_counter()
            try:
                response = await client.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=current_max_tokens,
                    response_format=response_format,
                )
            except ReasoningTokenLimitExceeded as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                call_attempts.append(
                    _call_attempt(
                        config,
                        attempt_index=attempt_index,
                        success=False,
                        elapsed_ms=elapsed_ms,
                        request_json=current_request_json,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                failures.append(f"{config.provider}/{config.model}: {exc}")
                if not retried[index] and _relaxed_max_tokens(max_tokens, config) is not None:
                    retried[index] = True
                    continue
                index += 1
                continue
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                call_attempts.append(
                    _call_attempt(
                        config,
                        attempt_index=attempt_index,
                        success=False,
                        elapsed_ms=elapsed_ms,
                        request_json=current_request_json,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                failures.append(f"{config.provider}/{config.model}: {exc}")
                index += 1
                continue

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if response_format == "json":
                try:
                    extract_json_object(response.content)
                except Exception as exc:
                    call_attempts.append(
                        _call_attempt(
                            config,
                            attempt_index=attempt_index,
                            success=False,
                            elapsed_ms=elapsed_ms,
                            request_json=current_request_json,
                            response_json=response.raw_response,
                            usage=response.usage,
                            error_type=type(exc).__name__,
                            error_message=f"Invalid JSON response: {exc}",
                        )
                    )
                    failures.append(
                        f"{config.provider}/{config.model}: invalid JSON response: {exc}"
                    )
                    index += 1
                    continue

            call_attempts.append(
                _call_attempt(
                    config,
                    attempt_index=attempt_index,
                    success=True,
                    elapsed_ms=elapsed_ms,
                    request_json=current_request_json,
                    response_json=response.raw_response,
                    usage=response.usage,
                )
            )
            return LLMResponse(
                content=response.content,
                provider=response.provider,
                model=response.model,
                raw_response=response.raw_response,
                usage=response.usage,
                call_attempts=call_attempts,
            )

        failure_text = " | ".join(failures)
        skipped_count = len(self.clients) - len(attempts)
        skipped_text = f" Skipped {skipped_count} fallback configs by limit." if skipped_count > 0 else ""
        raise LLMProviderError(
            f"All attempted LLM providers failed.{skipped_text} {failure_text}",
            call_attempts=call_attempts,
        )


def _relaxed_max_tokens(
    max_tokens: int | None,
    config: LLMProviderConfig,
) -> int | None:
    """推理模型 reasoning-only 重试时放宽后的 max_tokens。

    无推理预算配置（budget<=0）的供应商返回 None，表示不做同供应商放宽重试。
    放宽值 = 2 倍基础上限 + 推理预算，并封顶 32768 防止超大请求。
    """
    budget = config.reasoning_budget_tokens or 0
    if budget <= 0:
        return None
    return min((max_tokens or 1024) * 2 + budget, 32768)


def _request_json(
    messages: list[ChatMessage],
    *,
    temperature: float,
    max_tokens: int | None,
    response_format: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


def _call_attempt(
    config: LLMProviderConfig,
    *,
    attempt_index: int,
    success: bool,
    elapsed_ms: int,
    request_json: dict[str, Any],
    response_json: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    error_type: str = "",
    error_message: str = "",
) -> LLMCallAttempt:
    return LLMCallAttempt(
        provider=config.provider,
        model=config.model or "",
        api_url=config.api_url or "",
        protocol=str(config.protocol),
        attempt_index=attempt_index,
        success=success,
        elapsed_ms=elapsed_ms,
        request_json=request_json,
        response_json=response_json or {},
        usage=usage or {},
        error_type=error_type,
        error_message=error_message,
    )
