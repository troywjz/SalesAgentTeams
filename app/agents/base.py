import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.config import PROJECT_ROOT
from app.llm import ChatMessage, LLMCallAttempt, LLMClient, LLMProviderError
from app.utils.json_tools import extract_json_object


OutputKind = Literal["json", "text"]


@dataclass(frozen=True)
class AgentRunResult:
    agent_name: str
    output: dict[str, Any] | str
    raw_output: str
    input_payload: dict[str, Any]
    elapsed_ms: int
    provider: str
    model: str
    success: bool = True
    error_message: str = ""
    llm_call_attempts: list[LLMCallAttempt] = field(default_factory=list)


class AgentLLMProviderError(LLMProviderError):
    """保留失败 Agent 上下文，供服务层落库失败的 LLM fallback 尝试。"""

    def __init__(
        self,
        message: str,
        *,
        agent_name: str,
        input_payload: dict[str, Any],
        elapsed_ms: int,
        call_attempts: list[LLMCallAttempt],
    ) -> None:
        super().__init__(message, call_attempts=call_attempts)
        self.agent_name = agent_name
        self.input_payload = input_payload
        self.elapsed_ms = elapsed_ms


class BaseLLMAgent:
    name: str = "base_agent"
    prompt_file: str = ""
    output_kind: OutputKind = "json"
    temperature: float = 0.2
    max_tokens: int | None = None

    def __init__(
        self,
        llm_client: LLMClient,
        prompts_dir: Path | None = None,
        *,
        business_identity: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.prompts_dir = prompts_dir or PROJECT_ROOT / "prompts"
        self.business_identity = business_identity

    async def run(self, context: dict[str, Any]) -> AgentRunResult:
        system_prompt = self._load_prompt()
        user_prompt = self._build_user_prompt(context)
        started = time.perf_counter()
        try:
            response = await self.llm_client.chat(
                [
                    ChatMessage(
                        role="system",
                        content=f"[agent_name:{self.name}]\n{system_prompt}",
                    ),
                    ChatMessage(role="user", content=user_prompt),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format="json" if self.output_kind == "json" else None,
            )
        except LLMProviderError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise AgentLLMProviderError(
                str(exc),
                agent_name=self.name,
                input_payload=context,
                elapsed_ms=elapsed_ms,
                call_attempts=exc.call_attempts,
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        success = True
        error_message = ""
        if self.output_kind == "json":
            try:
                output: dict[str, Any] | str = extract_json_object(response.content)
            except (ValueError, json.JSONDecodeError) as exc:
                success = False
                error_message = f"JSON parse failed: {exc}"
                output = {
                    "_agent_error": "json_parse_failed",
                    "raw_output": response.content,
                }
        else:
            output = response.content.strip()

        return AgentRunResult(
            agent_name=self.name,
            output=output,
            raw_output=response.content,
            input_payload=context,
            elapsed_ms=elapsed_ms,
            provider=response.provider,
            model=response.model,
            success=success,
            error_message=error_message,
            llm_call_attempts=response.call_attempts,
        )

    def _load_prompt(self) -> str:
        if not self.prompt_file:
            raise ValueError(f"Agent '{self.name}' has no prompt_file configured.")
        path = self.prompts_dir / self.prompt_file
        prompt = path.read_text(encoding="utf-8")
        business_identity = self._load_business_identity()
        if not business_identity:
            return prompt
        return (
            "以下是当前业务身份配置。换行业、换公司、换销售身份时，"
            "优先修改 data/business/identity.md。\n"
            f"{business_identity}\n\n"
            "以下是当前 Agent 的任务提示词。\n"
            f"{prompt}"
        )

    def _load_business_identity(self) -> str:
        if self.business_identity is not None:
            return self.business_identity.strip()
        business_dir = PROJECT_ROOT / "data" / "business"
        for filename in ("identity.md", "identity.example.md"):
            path = business_dir / filename
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        return ""

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        return (
            "请基于以下上下文完成任务。\n"
            "上下文 JSON：\n"
            "```json\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}\n"
            "```"
        )
