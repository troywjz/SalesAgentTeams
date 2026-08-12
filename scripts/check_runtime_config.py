"""启动前检查公开展示配置，不输出任何密钥。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PROVIDER_FIELDS = {
    "minimax": ("MINIMAX_API_KEY", "MINIMAX_API_URL", "MINIMAX_MODEL", "MINIMAX_MODELS"),
    "aliyun": ("ALIYUN_API_KEY", "ALIYUN_API_URL", "ALIYUN_MODEL", "ALIYUN_MODELS"),
    "siliconflow": ("SILICONFLOW_API_KEY", "SILICONFLOW_API_URL", "SILICONFLOW_MODEL", "SILICONFLOW_MODELS"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_MODEL", "DEEPSEEK_MODELS"),
    "baiduqianfan": ("BAIDUQIANFAN_API_KEY", "BAIDUQIANFAN_API_URL", "BAIDUQIANFAN_MODEL", "BAIDUQIANFAN_MODELS"),
    "xiaomimimo": ("XIAOMIMIMO_API_KEY", "XIAOMIMIMO_API_URL", "XIAOMIMIMO_MODEL", "XIAOMIMIMO_MODELS"),
    "glm": ("ZHIPUAI_API_KEY", "GLM_API_URL", "GLM_MODEL", "GLM_MODELS"),
    "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_URL", "QWEN_MODEL", "QWEN_MODELS"),
    "chatgpt": ("OPENAI_API_KEY", "CHATGPT_API_URL", "CHATGPT_MODEL", "CHATGPT_MODELS"),
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_URL", "CLAUDE_MODEL", "CLAUDE_MODELS"),
}


def read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def validate_runtime_config(
    values: dict[str, str],
    *,
    skip_agentteams: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    demo_mode = _as_bool(values.get("DEMO_MODE", "true"))
    provider = values.get("LLM_PROVIDER", "demo").strip().lower()

    if "sales_agent_demo" not in values.get("DATABASE_URL", ""):
        errors.append("DATABASE_URL 必须指向隔离的 sales_agent_demo 数据库。")

    if demo_mode:
        notes.append("Web 当前为零 API 验证模式（DEMO_MODE=true）。")
    elif provider == "demo":
        errors.append("正式展示不能同时使用 DEMO_MODE=false 和 LLM_PROVIDER=demo。")
    else:
        errors.extend(_validate_provider(provider, values, label="主模型"))
        notes.append(f"Web 主模型：{provider}（真实 API）。")

    fallback_providers = _split_csv(values.get("LLM_PROVIDER_FALLBACK", ""))
    for fallback in fallback_providers:
        if fallback != provider:
            errors.extend(_validate_provider(fallback, values, label="备用模型"))

    attempt_limit = _positive_int(values.get("LLM_MAX_ATTEMPTS_PER_REQUEST", "1"))
    if attempt_limit is None:
        errors.append("LLM_MAX_ATTEMPTS_PER_REQUEST 必须是正整数。")
    elif fallback_providers and attempt_limit <= 1:
        notes.append("备用供应商已配置，但尝试上限为 1；默认不会产生额外备用调用。")

    vector_enabled = _as_bool(values.get("SALES_RAG_ENABLED", "false")) or _as_bool(
        values.get("SAFETY_VECTOR_ENABLED", "false")
    )
    if vector_enabled:
        embedding_provider = values.get("EMBEDDING_PROVIDER", "siliconflow").strip().lower()
        if not _embedding_key(embedding_provider, values):
            errors.append(f"已启用向量功能，但 Embedding 供应商 {embedding_provider} 缺少可用 API Key。")
        else:
            notes.append(f"向量功能使用 {embedding_provider} Embedding API。")
    else:
        notes.append("向量 RAG/风控默认关闭，启动不会额外调用 Embedding API。")

    agentteams_enabled = _as_bool(values.get("AGENTTEAMS_ENABLED", "true"))
    if demo_mode and provider == "demo" and agentteams_enabled and not skip_agentteams:
        errors.append("零 API 模式需要设置 AGENTTEAMS_ENABLED=false，或使用 start_all.ps1 -SkipAgentTeams。")
    elif not skip_agentteams and agentteams_enabled:
        if not _agentteams_key(values):
            agentteams_error = "AgentTeams 已启用，但缺少 AGENTTEAMS_LLM_API_KEY 或 Base URL 对应供应商的 Key。"
            primary_fields = PROVIDER_FIELDS.get(provider)
            primary_key_missing = bool(
                primary_fields and not values.get(primary_fields[0], "").strip()
            )
            # Web 和 AgentTeams 都复用同一供应商密钥时，只报告一次缺失项。
            if demo_mode or not primary_key_missing:
                errors.append(agentteams_error)
        model = values.get("AGENTTEAMS_DEFAULT_MODEL", "").strip()
        if not model:
            errors.append("AgentTeams 已启用，但 AGENTTEAMS_DEFAULT_MODEL 为空。")
        else:
            notes.append(f"AgentTeams 模型：{model}。")

    return errors, notes


def _validate_provider(provider: str, values: dict[str, str], *, label: str) -> list[str]:
    fields = PROVIDER_FIELDS.get(provider)
    if fields is None:
        return [f"{label}供应商不受支持：{provider}。"]
    key_name, url_name, model_name, models_name = fields
    missing: list[str] = []
    if not values.get(key_name, "").strip():
        missing.append(key_name)
    if not values.get(url_name, "").strip():
        missing.append(url_name)
    if not (values.get(model_name, "").strip() or values.get(models_name, "").strip()):
        missing.append(f"{model_name}/{models_name}")
    return [] if not missing else [f"{label} {provider} 缺少配置：{', '.join(missing)}。"]


def _agentteams_key(values: dict[str, str]) -> str:
    dedicated = values.get("AGENTTEAMS_LLM_API_KEY", "").strip()
    if dedicated:
        return dedicated
    provider = values.get("AGENTTEAMS_LLM_PROVIDER", "openai-compat").strip().lower()
    base_url = values.get("AGENTTEAMS_OPENAI_BASE_URL", "https://api.deepseek.com/v1").lower()
    if provider == "qwen":
        return values.get("DASHSCOPE_API_KEY", "").strip()
    if "deepseek" in base_url or provider == "deepseek":
        return values.get("DEEPSEEK_API_KEY", "").strip()
    if "siliconflow" in base_url:
        return values.get("SILICONFLOW_API_KEY", "").strip()
    if "dashscope" in base_url or "aliyun" in base_url:
        return values.get("ALIYUN_API_KEY", "").strip()
    return values.get("OPENAI_API_KEY", "").strip()


def _embedding_key(provider: str, values: dict[str, str]) -> str:
    if provider == "siliconflow":
        return values.get("SILICONFLOW_EMBEDDING_API_KEY", "").strip() or values.get("SILICONFLOW_API_KEY", "").strip()
    if provider == "aliyun":
        return values.get("ALIYUN_EMBEDDING_API_KEY", "").strip() or values.get("ALIYUN_API_KEY", "").strip()
    return ""


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 SalesAgentTeams 启动配置。")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--skip-agentteams", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise SystemExit(f"配置文件不存在：{args.env_file}")
    errors, notes = validate_runtime_config(
        read_env_values(args.env_file),
        skip_agentteams=args.skip_agentteams,
    )
    if errors:
        raise SystemExit("启动配置检查失败：\n- " + "\n- ".join(errors))
    print("启动配置检查通过：")
    for note in notes:
        print(f"- {note}")


if __name__ == "__main__":
    main()
