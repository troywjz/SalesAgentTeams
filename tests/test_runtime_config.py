import pytest

from app.core.config import Settings
from app.demo_data import _assert_demo_database_target
from app.llm import DemoLLMClient, create_llm_client


def test_windows_demo_defaults_to_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    # verify_demo.ps1 会用进程变量强制零 API；本测试需要隔离这些覆盖项，验证代码默认值。
    for name in (
        "DEMO_MODE",
        "LLM_PROVIDER",
        "LLM_PROVIDER_FALLBACK",
        "SALES_RAG_ENABLED",
        "SAFETY_VECTOR_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "sales_agent_demo" in settings.database_url
    assert settings.demo_seed_data is True
    assert settings.demo_mode is True
    assert settings.llm_provider == "demo"
    assert settings.llm_provider_fallback == "aliyun,siliconflow"
    assert settings.app_port == 18100
    assert settings.database_connect_timeout_seconds == 5
    assert settings.evaluation_max_concurrency == 3
    assert settings.llm_max_attempts_per_request == 3
    assert settings.sales_rag_enabled is False
    assert settings.llm_reasoning_budget_tokens == 0
    assert settings.llm_timeout_seconds == 90.0
    assert settings.chat_request_timeout_seconds == 300.0


def test_demo_mode_uses_local_llm() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
        DEMO_MODE=True,
        LLM_PROVIDER="demo",
    )

    assert isinstance(create_llm_client(settings), DemoLLMClient)


def test_missing_real_model_configuration_uses_demo_fallback() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
        DEMO_MODE=False,
        LLM_PROVIDER="minimax",
        LLM_PROVIDER_FALLBACK="deepseek",
    )

    assert isinstance(create_llm_client(settings), DemoLLMClient)


def test_configured_real_model_is_selected_before_demo() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
        DEMO_MODE=False,
        LLM_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="test-key",
        DEEPSEEK_MODEL="deepseek-chat",
    )

    from app.llm import FallbackLLMClient

    assert isinstance(create_llm_client(settings), FallbackLLMClient)


def test_demo_seed_rejects_non_demo_database() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent",
    )

    with pytest.raises(RuntimeError, match="非 Demo 数据库"):
        _assert_demo_database_target(settings)
