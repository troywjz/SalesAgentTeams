from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
import sys

from app.core.config import PROJECT_ROOT


ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class AdminConfigItem:
    key: str
    label: str
    group: str
    value_type: str
    default: str
    description: str
    requires_restart: bool = True


# 只允许修改不会暴露密钥、数据库连接串或认证根密钥的配置。
CONFIG_ITEMS = [
    AdminConfigItem("DEMO_MODE", "零 API 验证模式", "运行时配置", "bool", "false", "正式展示保持关闭；仅在测试或无密钥体验时开启本地确定性模型。"),
    AdminConfigItem("APP_RELOAD", "开发自动重载", "运行时配置", "bool", "false", "开发调试时是否启用 Uvicorn 自动重载。"),
    AdminConfigItem("LLM_PROVIDER", "主模型供应商", "模型配置", "string", "deepseek", "正式展示默认使用 DeepSeek；修改后需确保对应 API Key 已写入本机 .env。"),
    AdminConfigItem("LLM_PROVIDER_FALLBACK", "模型兜底顺序", "模型配置", "string", "aliyun,siliconflow", "默认在 DeepSeek 失败后依次尝试阿里云和 SiliconFlow。"),
    AdminConfigItem("MINIMAX_MODEL", "MiniMax 模型", "模型配置", "string", "MiniMax-M2.7", "MiniMax 供应商使用的模型名。"),
    AdminConfigItem("DEEPSEEK_MODEL", "DeepSeek 模型", "模型配置", "string", "deepseek-v4-flash", "DeepSeek 供应商使用的模型名。"),
    AdminConfigItem("ALIYUN_MODEL", "阿里云模型", "模型配置", "string", "deepseek-v4-flash-0731", "阿里云兼容接口使用的模型名。"),
    AdminConfigItem("SILICONFLOW_MODEL", "SiliconFlow 模型", "模型配置", "string", "deepseek-ai/DeepSeek-V4-Flash", "SiliconFlow 使用的模型名。"),
    AdminConfigItem("CHAT_REQUEST_TIMEOUT_SECONDS", "会话请求超时", "回复配置", "float", "300", "客户消息自动回复的最长等待秒数。"),
    AdminConfigItem("AI_REPLY_CHUNK_DELAY_SECONDS", "分段发送间隔", "回复配置", "float", "0.2", "拟人化分段发送时每段之间的等待秒数。"),
    AdminConfigItem("AI_REPLY_CHUNK_MAX_CHARS", "分段最大字数", "回复配置", "int", "45", "单段自动回复的最大字符数。"),
    AdminConfigItem("SAFETY_VECTOR_ENABLED", "风控向量审核", "风控配置", "bool", "false", "仅当风控规则有向量数据时启用向量审核。"),
    AdminConfigItem("SAFETY_VECTOR_THRESHOLD", "风控阈值", "风控配置", "float", "0.78", "风控向量匹配的触发阈值。"),
    AdminConfigItem("SAFETY_VECTOR_TOP_K", "风控召回数", "风控配置", "int", "3", "风控向量检索召回条数。"),
    AdminConfigItem("SALES_RAG_ENABLED", "销售案例 RAG", "RAG 配置", "bool", "true", "默认启用可替换销售案例的向量检索；向量服务不可用时主对话自动降级。"),
    AdminConfigItem("SALES_RAG_TOP_K", "案例召回数", "RAG 配置", "int", "3", "销售案例 RAG 检索条数。"),
    AdminConfigItem("SALES_RAG_MAX_REFERENCES", "案例注入条数", "RAG 配置", "int", "3", "注入回复生成的案例参考条数。"),
    AdminConfigItem("SALES_RAG_MIN_QUALITY_SCORE", "案例质量阈值", "RAG 配置", "float", "0.45", "可用案例片段的最低质量分。"),
    AdminConfigItem("KNOWLEDGE_AUTO_IMPORT", "启动时导入知识", "知识库配置", "bool", "false", "服务启动时是否重新导入公开知识示例。"),
    AdminConfigItem("SOP_FOLLOWUP_ENABLED", "SOP 自动跟进", "SOP 配置", "bool", "true", "是否启用 SOP 超时自动跟进任务。"),
    AdminConfigItem("SOP_FOLLOWUP_POLL_INTERVAL_SECONDS", "跟进扫描间隔", "SOP 配置", "float", "5", "SOP 自动跟进任务扫描间隔秒数。"),
    AdminConfigItem("SOP_FOLLOWUP_BATCH_SIZE", "跟进批次大小", "SOP 配置", "int", "10", "每轮最多处理的跟进任务数。"),
]

CONFIG_BY_KEY = {item.key: item for item in CONFIG_ITEMS}


class AdminConfigService:
    def __init__(self, env_file: Path = ENV_FILE) -> None:
        self.env_file = env_file

    def list_items(self) -> dict[str, object]:
        values = self._read_env_values()
        return {
            "env_file": str(self.env_file),
            "items": [
                {
                    "key": item.key,
                    "label": item.label,
                    "group": item.group,
                    "type": item.value_type,
                    "value": values.get(item.key, item.default),
                    "default": item.default,
                    "description": item.description,
                    "requires_restart": item.requires_restart,
                }
                for item in CONFIG_ITEMS
            ],
        }

    def update_items(self, updates: dict[str, object]) -> dict[str, object]:
        normalized = {
            key: self._normalize_value(CONFIG_BY_KEY[key], value)
            for key, value in updates.items()
            if key in CONFIG_BY_KEY
        }
        rejected = sorted(set(updates) - set(CONFIG_BY_KEY))
        if not normalized and rejected:
            raise ValueError(f"没有可保存的白名单配置项：{', '.join(rejected)}")

        lines = self._read_env_lines()
        existing_indexes: dict[str, int] = {}
        for index, line in enumerate(lines):
            key = self._line_key(line)
            if key:
                existing_indexes[key] = index

        for key, value in normalized.items():
            rendered = f"{key}={_quote_env_value(value)}\n"
            if key in existing_indexes:
                lines[existing_indexes[key]] = rendered
            else:
                if lines and lines[-1].strip():
                    lines.append("\n")
                lines.append(rendered)

        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text("".join(lines), encoding="utf-8", newline="\n")
        return {
            "saved": sorted(normalized),
            "rejected": rejected,
            "requires_restart": True,
            "env_file": str(self.env_file),
        }

    def restart(self) -> dict[str, object]:
        """安排当前 Windows Python 服务自替换，重新加载刚写入的 .env。"""
        _schedule_process_restart()
        return {
            "ok": True,
            "mode": "windows_python_process",
            "message": "配置已保存，Windows Python 服务将在短暂延迟后重启。",
        }

    def _read_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in self._read_env_lines():
            key = self._line_key(line)
            if key:
                values[key] = _unquote_env_value(line.split("=", 1)[1].strip())
        return values

    def _read_env_lines(self) -> list[str]:
        if not self.env_file.exists():
            return []
        return self.env_file.read_text(encoding="utf-8").splitlines(keepends=True)

    @staticmethod
    def _line_key(line: str) -> str:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return ""
        key = stripped.split("=", 1)[0].strip()
        return key if key.isidentifier() else ""

    @staticmethod
    def _normalize_value(item: AdminConfigItem, value: object) -> str:
        text_value = str(value).strip()
        if item.value_type == "bool":
            lowered = text_value.lower()
            if lowered in {"true", "1", "yes", "on"}:
                return "true"
            if lowered in {"false", "0", "no", "off"}:
                return "false"
            raise ValueError(f"{item.key} 必须是布尔值。")
        if item.value_type == "int":
            value_int = int(text_value)
            if value_int < 0:
                raise ValueError(f"{item.key} 不能是负数。")
            return str(value_int)
        if item.value_type == "float":
            value_float = float(text_value)
            if value_float < 0:
                raise ValueError(f"{item.key} 不能是负数。")
            return str(value_float)
        return text_value


def _quote_env_value(value: str) -> str:
    if not value:
        return ""
    if any(char.isspace() for char in value) or "#" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _schedule_process_restart() -> None:
    # 给 Uvicorn 完成当前 HTTP 响应留出时间，再替换进程并重新读取 .env。
    timer = threading.Timer(2.0, _restart_current_process)
    timer.daemon = True
    timer.start()


def _restart_current_process() -> None:
    args = [sys.executable, *sys.argv]
    if len(args) == 1:
        args.extend(["-m", "app.main"])
    subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )
    # 新进程已启动后退出旧进程，释放 HTTP 端口；新进程会重新读取 .env。
    os._exit(0)
