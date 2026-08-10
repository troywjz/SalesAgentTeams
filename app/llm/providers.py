from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


class LLMProtocol(StrEnum):
    openai_chat = "openai_chat"
    anthropic_messages = "anthropic_messages"


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: str
    api_url: str | None
    api_key: str | None
    model: str | None
    protocol: LLMProtocol
    timeout_seconds: float
    anthropic_version: str | None = None
    # 推理模型（如 deepseek 推理版）的 reasoning token 预留预算：叠加到请求
    # max_tokens 上；预算 >0 时，reasoning-only 响应还会触发同供应商放宽重试。
    reasoning_budget_tokens: int = 0


def build_llm_fallback_configs(settings: Settings) -> list[LLMProviderConfig]:
    primary_provider = settings.llm_provider.strip().lower()
    provider_order = _ordered_providers(primary_provider, settings.llm_provider_fallback)
    provider_configs = _provider_config_map(settings)
    configs: list[LLMProviderConfig] = []

    for provider_name in provider_order:
        provider_config = provider_configs.get(provider_name)
        if provider_config is None:
            continue
        configs.extend(provider_config)

    return configs


def _provider_config_map(settings: Settings) -> dict[str, list[LLMProviderConfig]]:
    return {
        "baiduqianfan": _expand_provider_models(
            provider="baiduqianfan",
            api_url=_blank_to_none(settings.baiduqianfan_api_url),
            api_key=_blank_to_none(settings.baiduqianfan_api_key),
            models=_split_models(
                settings.baiduqianfan_models,
                settings.baiduqianfan_model,
            ),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "minimax": _expand_provider_models(
            provider="minimax",
            api_url=_blank_to_none(settings.minimax_api_url),
            api_key=_blank_to_none(settings.minimax_api_key),
            models=_split_models(settings.minimax_models, settings.minimax_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "xiaomimimo": _expand_provider_models(
            provider="xiaomimimo",
            api_url=_blank_to_none(settings.xiaomimimo_api_url),
            api_key=_blank_to_none(settings.xiaomimimo_api_key),
            models=_split_models(
                settings.xiaomimimo_models,
                settings.xiaomimimo_model,
            ),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "aliyun": _expand_provider_models(
            provider="aliyun",
            api_url=_blank_to_none(settings.aliyun_api_url),
            api_key=_blank_to_none(settings.aliyun_api_key),
            models=_split_models(settings.aliyun_models, settings.aliyun_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "siliconflow": _expand_provider_models(
            provider="siliconflow",
            api_url=_blank_to_none(settings.siliconflow_api_url),
            api_key=_blank_to_none(settings.siliconflow_api_key),
            models=_split_models(settings.siliconflow_models, settings.siliconflow_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "glm": _expand_provider_models(
            provider="glm",
            api_url=_blank_to_none(settings.glm_api_url),
            api_key=_blank_to_none(settings.zhipuai_api_key),
            models=_split_models(settings.glm_models, settings.glm_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "deepseek": _expand_provider_models(
            provider="deepseek",
            api_url=_blank_to_none(settings.deepseek_api_url),
            api_key=_blank_to_none(settings.deepseek_api_key),
            models=_split_models(settings.deepseek_models, settings.deepseek_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "qwen": _expand_provider_models(
            provider="qwen",
            api_url=_blank_to_none(settings.qwen_api_url),
            api_key=_blank_to_none(settings.dashscope_api_key),
            models=_split_models(settings.qwen_models, settings.qwen_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "chatgpt": _expand_provider_models(
            provider="chatgpt",
            api_url=_blank_to_none(settings.chatgpt_api_url),
            api_key=_blank_to_none(settings.openai_api_key),
            models=_split_models(settings.chatgpt_models, settings.chatgpt_model),
            protocol=LLMProtocol.openai_chat,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_budget_tokens=settings.llm_reasoning_budget_tokens,
        ),
        "claude": _expand_provider_models(
            provider="claude",
            api_url=_blank_to_none(settings.claude_api_url),
            api_key=_blank_to_none(settings.anthropic_api_key),
            models=_split_models(settings.claude_models, settings.claude_model),
            protocol=LLMProtocol.anthropic_messages,
            timeout_seconds=settings.llm_timeout_seconds,
            anthropic_version=settings.anthropic_version,
        ),
    }


def _ordered_providers(primary_provider: str, provider_fallback: str | None) -> list[str]:
    fallback = _split_csv(provider_fallback)
    ordered = [primary_provider]
    ordered.extend(p for p in fallback if p != primary_provider)
    return list(dict.fromkeys(ordered))


def _expand_provider_models(
    *,
    provider: str,
    api_url: str | None,
    api_key: str | None,
    models: list[str],
    protocol: LLMProtocol,
    timeout_seconds: float,
    anthropic_version: str | None = None,
    reasoning_budget_tokens: int = 0,
) -> list[LLMProviderConfig]:
    if not api_url or not api_key or not models:
        return []
    return [
        LLMProviderConfig(
            provider=provider,
            api_url=api_url,
            api_key=api_key,
            model=model,
            protocol=protocol,
            timeout_seconds=timeout_seconds,
            anthropic_version=anthropic_version,
            reasoning_budget_tokens=reasoning_budget_tokens,
        )
        for model in models
    ]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _split_models(models_value: str | None, single_model: str | None) -> list[str]:
    models = [item.strip() for item in (models_value or "").split(",") if item.strip()]
    single = _blank_to_none(single_model)
    if single:
        models.insert(0, single)
    return list(dict.fromkeys(models))
