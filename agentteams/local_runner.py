"""不依赖 AgentTeams 基础设施的六 Worker 本地演示运行器。"""

from __future__ import annotations

from typing import Any

from app.llm import DemoLLMClient

from sales_agent_teams.bridge import SalesAgentBridge
from sales_agent_teams.contracts import AgentRequest, AgentResponse


class LocalSalesTeam:
    """用同一份 Worker 契约复现 AgentTeams 的最小可验证协作链路。"""

    def __init__(self) -> None:
        self.bridge = SalesAgentBridge(DemoLLMClient(delay_ms=0))

    async def run_turn(
        self,
        message: str,
        *,
        conversation_id: str = "local-demo",
        turn_id: str = "turn-1",
        conversation_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = dict(conversation_state or {})
        trace: list[AgentResponse] = []

        async def call(worker_id: str, *, mode: str = "run", extra: dict[str, Any] | None = None) -> AgentResponse:
            request = AgentRequest(
                task_id=f"{conversation_id}:{turn_id}",
                conversation_id=conversation_id,
                turn_id=turn_id,
                message=message,
                conversation_state={**state, **(extra or {})},
                mode=mode,  # type: ignore[arg-type]
            )
            response = await self.bridge.run(worker_id, request)
            trace.append(response)
            if isinstance(response.output, dict):
                state[worker_id.removesuffix("_worker")] = response.output
            return response

        await call("memory_worker", mode="load")
        intent = await call("intent_worker")
        sop = await call("sop_worker", extra={"intent": intent.output})
        knowledge = await call(
            "knowledge_worker",
            extra={"intent": intent.output, "sop_decision": sop.output},
        )
        conversation = await call(
            "conversation_worker",
            extra={
                "intent": intent.output,
                "sop_decision": sop.output,
                "knowledge_context": knowledge.output,
            },
        )
        safety = await call(
            "safety_worker",
            extra={
                "intent": intent.output,
                "sop_decision": sop.output,
                "draft_reply": conversation.output.get("final_reply", "")
                if isinstance(conversation.output, dict)
                else str(conversation.output),
            },
        )
        await call(
            "memory_worker",
            mode="update",
            extra={"turn_outputs": {item.worker_id: item.output for item in trace}},
        )
        final_reply = ""
        if isinstance(safety.output, dict):
            final_reply = str(safety.output.get("approved_reply") or safety.output.get("revised_reply") or "")
        if not final_reply and isinstance(conversation.output, dict):
            final_reply = str(conversation.output.get("final_reply") or "")
        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "final_reply": final_reply,
            "handoff": safety.handoff.model_dump(mode="json"),
            "trace": [item.model_dump(mode="json") for item in trace],
        }
