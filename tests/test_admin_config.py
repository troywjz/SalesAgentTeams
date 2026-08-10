from pathlib import Path

from app.services import admin_config_service
from app.services.admin_config_service import AdminConfigService


def test_admin_config_saves_utf8_whitelisted_values_and_restarts(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# 演示配置\nLLM_PROVIDER=minimax\n", encoding="utf-8")
    restart_called = []
    monkeypatch.setattr(
        admin_config_service,
        "_schedule_process_restart",
        lambda: restart_called.append(True),
    )
    service = AdminConfigService(env_file)

    result = service.update_items(
        {
            "LLM_PROVIDER": "deepseek",
            "SALES_RAG_ENABLED": False,
            "UNKNOWN_SECRET": "should-be-rejected",
        }
    )
    restart_result = service.restart()

    content = env_file.read_text(encoding="utf-8")
    assert "LLM_PROVIDER=deepseek" in content
    assert "SALES_RAG_ENABLED=false" in content
    assert "UNKNOWN_SECRET" not in content
    assert result["rejected"] == ["UNKNOWN_SECRET"]
    assert restart_result["ok"] is True
    assert restart_result["mode"] == "windows_python_process"
    assert restart_called == [True]
