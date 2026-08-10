"""Large language model provider adapters."""
from app.llm.base import (
    ChatMessage,
    LLMCallAttempt,
    LLMClient,
    LLMConfigurationError,
    LLMProviderError,
    LLMResponse,
)
from app.llm.fallback_client import FallbackLLMClient
from app.llm.demo_client import DemoLLMClient
from app.llm.embedding import (
    EmbeddingCallAttempt,
    EmbeddingClient,
    EmbeddingProviderConfig,
    EmbeddingResponse,
    FallbackEmbeddingClient,
    build_embedding_fallback_configs,
    create_embedding_client,
)
from app.llm.factory import create_llm_client
from app.llm.providers import LLMProtocol, LLMProviderConfig, build_llm_fallback_configs

__all__ = [
    "ChatMessage",
    "LLMCallAttempt",
    "LLMClient",
    "LLMConfigurationError",
    "LLMProviderError",
    "LLMResponse",
    "LLMProtocol",
    "LLMProviderConfig",
    "FallbackLLMClient",
    "DemoLLMClient",
    "EmbeddingCallAttempt",
    "EmbeddingClient",
    "EmbeddingProviderConfig",
    "EmbeddingResponse",
    "FallbackEmbeddingClient",
    "build_embedding_fallback_configs",
    "create_embedding_client",
    "build_llm_fallback_configs",
    "create_llm_client",
]
