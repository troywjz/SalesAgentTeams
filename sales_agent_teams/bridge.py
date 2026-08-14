"""将六个 Worker 的结构化请求适配到原项目 Agent 实现。"""

from __future__ import annotations

from typing import Any

from app.agents import (
    ConversationAgent,
    IntentAgent,
    KnowledgeAgent,
    MemoryAgent,
    SafetyAgent,
    SOPAgent,
)
from app.llm import LLMClient

from .contracts import AgentRequest, AgentResponse, Handoff


WORKER_SKILLS = {
    "intent_worker": "intent-classification@1.1.1",
    "sop_worker": "sop-decision@1.1.1",
    "knowledge_worker": "knowledge-grounding@1.1.1",
    "conversation_worker": "reply-drafting@1.1.0",
    "safety_worker": "safety-review@1.1.0",
    "memory_worker": "memory-update@1.1.0",
}


class SalesAgentBridge:
    """只允许 Worker 调用其对应的业务 Agent。"""

    def __init__(self, llm_client: LLMClient) -> None:
        self._agents = {
            "intent_worker": IntentAgent(llm_client),
            "sop_worker": SOPAgent(llm_client),
            "knowledge_worker": KnowledgeAgent(llm_client),
            "conversation_worker": ConversationAgent(llm_client),
            "safety_worker": SafetyAgent(llm_client),
            "memory_worker": MemoryAgent(llm_client),
        }

    async def run(self, worker_id: str, request: AgentRequest) -> AgentResponse:
        if worker_id not in self._agents:
            raise ValueError(f"未知 Worker: {worker_id}")
        context: dict[str, Any] = {
            "task_id": request.task_id,
            "conversation_id": request.conversation_id,
            "turn_id": request.turn_id,
            "message": request.message,
            "conversation_state": request.conversation_state,
            "allowed_knowledge_refs": request.allowed_knowledge_refs,
            "mode": request.mode,
        }
        result = await self._agents[worker_id].run(context)
        output = result.output if isinstance(result.output, (dict, str)) else str(result.output)
        status = "success" if result.success else "failed"
        if worker_id == "safety_worker" and isinstance(output, dict) and output.get("handover_required"):
            status = "handoff"
        handoff = Handoff(
            required=status == "handoff",
            target="human_sales" if status == "handoff" else None,
            reason=str(output.get("reason", "安全审核要求人工接管")) if isinstance(output, dict) and status == "handoff" else None,
        )
        return AgentResponse(
            task_id=request.task_id,
            worker_id=worker_id,
            skill_version=WORKER_SKILLS[worker_id],
            status=status,
            output=output,
            evidence_refs=[f"agent://{result.agent_name}/{request.turn_id}"],
            handoff=handoff,
            error=result.error_message or None,
        )
