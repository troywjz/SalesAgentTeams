from pathlib import Path

from scripts.check_runtime_config import read_env_values, validate_runtime_config


ROOT = Path(__file__).resolve().parents[1]


def test_public_template_only_requires_recommended_api_key() -> None:
    values = read_env_values(ROOT / ".env.example")

    errors, _ = validate_runtime_config(values)

    assert errors == [
        "主模型 deepseek 缺少配置：DEEPSEEK_API_KEY。",
    ]

    values["DEEPSEEK_API_KEY"] = "test-key"
    errors, notes = validate_runtime_config(values)

    assert errors == []
    assert "Web 主模型：deepseek（真实 API）。" in notes
    assert "AgentTeams 模型：deepseek-v4-flash。" in notes


def test_preflight_rejects_silent_demo_fallback() -> None:
    values = read_env_values(ROOT / ".env.example")
    values.update(
        {
            "DEMO_MODE": "false",
            "LLM_PROVIDER": "demo",
            "AGENTTEAMS_ENABLED": "false",
        }
    )

    errors, _ = validate_runtime_config(values)

    assert "正式展示不能同时使用 DEMO_MODE=false 和 LLM_PROVIDER=demo。" in errors


def test_preflight_allows_explicit_zero_api_mode_without_model_key() -> None:
    values = read_env_values(ROOT / ".env.example")
    values.update(
        {
            "DEMO_MODE": "true",
            "LLM_PROVIDER": "demo",
            "AGENTTEAMS_ENABLED": "false",
        }
    )

    errors, notes = validate_runtime_config(values)

    assert errors == []
    assert "Web 当前为零 API 验证模式（DEMO_MODE=true）。" in notes


def test_preflight_honors_skip_agentteams() -> None:
    values = read_env_values(ROOT / ".env.example")
    values["DEEPSEEK_API_KEY"] = "test-key"
    values["AGENTTEAMS_OPENAI_BASE_URL"] = "https://example.com/v1"

    errors, _ = validate_runtime_config(values, skip_agentteams=True)

    assert errors == []
