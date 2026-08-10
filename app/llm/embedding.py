from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.llm.base import LLMConfigurationError, LLMProviderError


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    provider: str
    api_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float
    column_name: str


@dataclass(frozen=True)
class EmbeddingCallAttempt:
    """单次 Embedding 调用尝试，用于记录向量审核的 fallback 链路。"""

    provider: str
    model: str
    api_url: str
    attempt_index: int
    success: bool
    elapsed_ms: int
    input_text: str
    embedding_dimension: int = 0
    request_json: dict[str, Any] = field(default_factory=dict)
    response_json: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class EmbeddingResponse:
    embedding: list[float]
    provider: str
    model: str
    column_name: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    call_attempts: list[EmbeddingCallAttempt] = field(default_factory=list)


class EmbeddingClient(Protocol):
    async def embed(self, text: str) -> EmbeddingResponse:
        ...


class HttpEmbeddingClient:
    def __init__(self, config: EmbeddingProviderConfig) -> None:
        self.config = config

    async def embed(self, text: str) -> EmbeddingResponse:
        self._validate_config()
        payload: dict[str, Any] = {"model": self.config.model, "input": text}
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }
        raw = await self._post_json(self._embedding_url(), payload, headers)
        embedding = _extract_embedding(raw)
        return EmbeddingResponse(
            embedding=embedding,
            provider=self.config.provider,
            model=self.config.model or "",
            column_name=self.config.column_name,
            raw_response=raw,
            usage=raw.get("usage") or {},
        )

    def _validate_config(self) -> None:
        missing: list[str] = []
        if not self.config.api_url:
            missing.append("api_url")
        if not self.config.api_key:
            missing.append("api_key")
        if not self.config.model:
            missing.append("model")
        if missing:
            raise LLMConfigurationError(
                f"Embedding provider '{self.config.provider}' is missing: {', '.join(missing)}."
            )

    async def _post_json(
        self,
        api_url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        try:
            # trust_env=False：本项目 LLM/Embedding 供应商均为国内 API，必须直连，
            # 不读环境变量代理。否则代理软件一关，请求会被强制发往本地代理端口导致
            # ConnectionRefused。接入境外供应商时需另行显式配置代理。
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds, trust_env=False
            ) as client:
                response = await client.post(api_url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            text_value = exc.response.text[:1000]
            raise LLMProviderError(
                f"Embedding provider '{self.config.provider}' returned "
                f"HTTP {exc.response.status_code}: {text_value}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"Embedding provider '{self.config.provider}' request failed: {exc}"
            ) from exc

    def _embedding_url(self) -> str:
        api_url = (self.config.api_url or "").rstrip("/")
        if api_url.endswith("/embeddings"):
            return api_url
        return f"{api_url}/embeddings"


class FallbackEmbeddingClient:
    def __init__(self, configs: list[EmbeddingProviderConfig]) -> None:
        self.configs = configs
        self.clients = [HttpEmbeddingClient(config) for config in configs]

    async def embed(self, text: str) -> EmbeddingResponse:
        if not self.clients:
            raise LLMProviderError("No configured embedding providers available.")

        attempts: list[EmbeddingCallAttempt] = []
        failures: list[str] = []
        request_json = {"input": text}
        for attempt_index, (config, client) in enumerate(
            zip(self.configs, self.clients, strict=True),
            start=1,
        ):
            started = time.perf_counter()
            try:
                response = await client.embed(text)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                attempts.append(
                    _call_attempt(
                        config,
                        attempt_index=attempt_index,
                        success=False,
                        elapsed_ms=elapsed_ms,
                        input_text=text,
                        request_json={**request_json, "model": config.model},
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                failures.append(f"{config.provider}/{config.model}: {exc}")
                continue

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            attempts.append(
                _call_attempt(
                    config,
                    attempt_index=attempt_index,
                    success=True,
                    elapsed_ms=elapsed_ms,
                    input_text=text,
                    embedding_dimension=len(response.embedding),
                    request_json={**request_json, "model": config.model},
                    response_json=response.raw_response,
                    usage=response.usage,
                )
            )
            return EmbeddingResponse(
                embedding=response.embedding,
                provider=response.provider,
                model=response.model,
                column_name=response.column_name,
                raw_response=response.raw_response,
                usage=response.usage,
                call_attempts=attempts,
            )

        raise LLMProviderError(
            "All attempted embedding providers failed. " + " | ".join(failures),
            call_attempts=attempts,
        )


def create_embedding_client(settings: Settings | None = None) -> EmbeddingClient:
    settings = settings or get_settings()
    return FallbackEmbeddingClient(build_embedding_fallback_configs(settings))


def build_embedding_fallback_configs(settings: Settings) -> list[EmbeddingProviderConfig]:
    primary = settings.embedding_provider.strip().lower()
    providers = _ordered_providers(primary, settings.embedding_provider_fallback)
    config_map = {
        "siliconflow": EmbeddingProviderConfig(
            provider="siliconflow",
            api_url=settings.siliconflow_embedding_api_url,
            api_key=settings.siliconflow_embedding_api_key or settings.siliconflow_api_key,
            model=settings.siliconflow_embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            column_name="violation_embedding_gjld_q3e8b",
        ),
        "aliyun": EmbeddingProviderConfig(
            provider="aliyun",
            api_url=settings.aliyun_embedding_api_url,
            api_key=settings.aliyun_embedding_api_key or settings.aliyun_api_key,
            model=settings.aliyun_embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            column_name="violation_embedding_albl_tev4",
        ),
    }
    return [config_map[name] for name in providers if name in config_map]


def _ordered_providers(primary_provider: str, provider_fallback: str | None) -> list[str]:
    fallback = [
        item.strip().lower()
        for item in (provider_fallback or "").split(",")
        if item.strip()
    ]
    ordered = [primary_provider]
    ordered.extend(item for item in fallback if item != primary_provider)
    return list(dict.fromkeys(ordered))


def _extract_embedding(raw: dict[str, Any]) -> list[float]:
    try:
        value = raw["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError("Unexpected embedding response shape.") from exc
    if not isinstance(value, list):
        raise LLMProviderError("Embedding response is not a list.")
    return [float(item) for item in value]


def _call_attempt(
    config: EmbeddingProviderConfig,
    *,
    attempt_index: int,
    success: bool,
    elapsed_ms: int,
    input_text: str,
    embedding_dimension: int = 0,
    request_json: dict[str, Any] | None = None,
    response_json: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    error_type: str = "",
    error_message: str = "",
) -> EmbeddingCallAttempt:
    return EmbeddingCallAttempt(
        provider=config.provider,
        model=config.model or "",
        api_url=config.api_url or "",
        attempt_index=attempt_index,
        success=success,
        elapsed_ms=elapsed_ms,
        input_text=input_text,
        embedding_dimension=embedding_dimension,
        request_json=request_json or {},
        response_json=response_json or {},
        usage=usage or {},
        error_type=error_type,
        error_message=error_message,
    )
