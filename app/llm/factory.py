from app.core.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.demo_client import DemoLLMClient
from app.llm.fallback_client import FallbackLLMClient
from app.llm.providers import build_llm_fallback_configs


def create_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    configs = build_llm_fallback_configs(settings)
    if (
        settings.demo_mode
        or settings.llm_provider.strip().lower() == "demo"
        or not configs
    ):
        return DemoLLMClient(delay_ms=settings.demo_agent_delay_ms)
    return FallbackLLMClient(
        configs,
        max_attempts=settings.llm_max_attempts_per_request,
    )
