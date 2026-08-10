from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.agents import AgentRunResult, MemoryAgent
from app.conversation import ConversationState, CustomerProfile
from app.core.time import to_beijing_time, to_utc_time
from app.graph.nodes import (
    _apply_profile_update,
    _as_dict,
    _extract_memory_summary,
    route_after_intent,
    route_after_knowledge,
    route_after_safety,
    route_after_supervisor,
    serialize_run,
)
from app.graph.sales_graph import build_sales_graph
from app.graph.state import SalesGraphState
from app.knowledge import KnowledgeLoader
from app.llm import LLMClient, LLMProviderError
from app.core.config import Settings
from app.repositories import ChatRepository


# 会话级字段名列表，用于在图状态和 ConversationState 之间转换
_SESSION_FIELDS = (
    "session_id",
    "customer_id",
    "current_stage",
    "customer_profile",
    "history_summary",
    "message_count",
    "transfer_flag",
    "transfer_reason",
)


@dataclass(frozen=True)
class GraphChatTurnResult:
    reply: str
    state: ConversationState
    agent_runs: list[dict[str, Any]]


@dataclass(frozen=True)
class GraphStateResult:
    state: ConversationState
    agent_runs: list[dict[str, Any]]


NODE_LABELS = {
    "init": "初始化状态",
    "supervisor_router": "调度路由",
    "intent": "意图识别",
    "sop": "SOP 流程决策",
    "knowledge": "知识匹配",
    "sales_case_rag": "销售案例检索",
    "context_gate": "上下文汇聚",
    "conversation": "生成回复",
    "safety": "风控审核",
    "rewrite_reply": "风控改写",
    "handover": "转人工",
    "final_reply": "最终回复",
    "send": "发送回复",
    "finalize": "整理状态",
    "memory_update": "记忆更新",
    "sales_graph": "系统转人工",
}

NODE_RUNNING_STATUS = {
    "init": "正在加载商品、FAQ、SOP 与风控规则",
    "supervisor_router": "正在判断本轮对话处理路径",
    "intent": "正在识别客户意图、意向和情绪",
    "sop": "正在进行 SOP 流程决策",
    "knowledge": "正在匹配商品与业务知识",
    "sales_case_rag": "正在检索可借鉴的优秀销售案例",
    "context_gate": "正在汇总 SOP 与知识库结果",
    "conversation": "正在生成回复草稿",
    "safety": "正在进行风控审核",
    "rewrite_reply": "正在按风控结果改写回复",
    "handover": "正在生成转人工交接信息",
    "final_reply": "正在生成最终回复",
    "send": "正在发送回复",
    "finalize": "正在保存会话状态",
    "memory_update": "正在更新客户画像和压缩记忆",
    "sales_graph": "正在转人工处理",
}

AGENT_NODE_BY_RUN = {
    "intent_agent": "intent",
    "memory_agent": "memory_update",
    "sop_agent": "sop",
    "knowledge_agent": "knowledge",
    "conversation_agent": "conversation",
    "safety_agent": "safety",
    "sales_case_rag": "sales_case_rag",
    "sales_graph": "sales_graph",
}

_ACTIVE_STREAM_TASKS: dict[str, asyncio.Task[Any]] = {}


def _pack_graph_state(
    state: ConversationState,
    message: str,
    *,
    turn_id: str = "",
) -> SalesGraphState:
    """将 ConversationState + message 打包为 SalesGraphState 顶层字段。"""
    return {
        "message": message,
        "session_id": state.session_id,
        "turn_id": turn_id,
        "customer_id": state.customer_id,
        "current_stage": state.current_stage,
        "customer_profile": state.customer_profile,
        "history_summary": state.history_summary,
        "message_count": state.message_count,
        "transfer_flag": state.transfer_flag,
        "transfer_reason": state.transfer_reason,
        "intent": None,
        "sop": None,
        "knowledge_output": None,
        "knowledge_sufficiency": None,
        "sales_case_references": [],
        "safety": None,
        "safety_retry_count": 0,
        "draft_reply": None,
        "reply": "",
        "sent_reply": False,
        "runs": [],
    }


def _unpack_graph_state(graph_state: SalesGraphState) -> ConversationState:
    """从 SalesGraphState 顶层字段重建 ConversationState。"""
    return ConversationState(
        session_id=graph_state.get("session_id", ""),
        customer_id=graph_state.get("customer_id", ""),
        current_stage=graph_state.get("current_stage", "开场"),
        customer_profile=graph_state.get("customer_profile") or CustomerProfile(),
        history_summary=graph_state.get("history_summary", ""),
        message_count=graph_state.get("message_count", 0),
        transfer_flag=graph_state.get("transfer_flag", False),
        transfer_reason=graph_state.get("transfer_reason", ""),
    )


def _apply_sop_stage_from_runs(
    state: ConversationState,
    runs: list[AgentRunResult],
) -> ConversationState:
    """从本轮 SOPAgent 输出兜底恢复销售阶段。

    LangGraph 并行节点最终合并时可能保留旧顶层阶段；SOP run 是本轮
    阶段决策的事实来源，因此服务层落库前再对齐一次。
    """
    for run in reversed(runs):
        if run.agent_name != "sop_agent" or not isinstance(run.output, dict):
            continue
        stage = str(run.output.get("current_stage") or "").strip()
        if not stage:
            continue
        if stage in {"handover", "closed", "转人工", "已结束", "结束"}:
            return state
        if stage == state.current_stage:
            return state
        updated = state.model_copy(deep=True)
        updated.current_stage = stage
        updated.touch()
        return updated
    return state


class GraphSessionStore:
    def __init__(self, repository: ChatRepository | None = None) -> None:
        self._states: dict[str, ConversationState] = {}
        self.repository = repository

    def get_or_create(self, session_id: str | None = None) -> ConversationState:
        if session_id and session_id in self._states:
            return self._states[session_id]

        if session_id and self.repository is not None:
            stored_state = self.repository.get_state(session_id)
            if stored_state is not None:
                self._states[session_id] = stored_state
                return stored_state

        state = ConversationState(
            session_id=session_id or str(uuid4()),
            customer_id=str(uuid4()),
        )
        self._states[state.session_id] = state
        return state

    def reset(self, session_id: str) -> ConversationState:
        state = ConversationState(session_id=session_id, customer_id=str(uuid4()))
        self._states[session_id] = state
        if self.repository is not None:
            self.repository.clear_session_activity(session_id)
            self.repository.save_state(state)
            self.repository.commit()
        return state

    def save(self, state: ConversationState) -> ConversationState:
        """保存进程内会话快照，供无数据库调用链继续下一轮。"""
        saved = state.model_copy(deep=True)
        self._states[saved.session_id] = saved
        return saved.model_copy(deep=True)


class SalesGraphService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        session_store: GraphSessionStore | None = None,
        knowledge_loader: KnowledgeLoader | None = None,
        repository: ChatRepository | None = None,
        sales_case_rag_service: Any | None = None,
        safety_vector_reviewer: Any | None = None,
        settings: Settings | None = None,
        enable_checkpoint: bool = True,
        request_timeout_seconds: float = 120.0,
        include_memory_update: bool = True,
    ) -> None:
        self.repository = repository
        self.session_store = session_store or GraphSessionStore(repository)
        self.knowledge_loader = knowledge_loader or KnowledgeLoader()
        self.graph = build_sales_graph(
            llm_client,
            self.knowledge_loader,
            sales_case_rag_service,
            safety_vector_reviewer=safety_vector_reviewer,
            settings=settings,
            enable_checkpoint=enable_checkpoint,
            include_memory_update=include_memory_update,
        )
        self.memory_agent = MemoryAgent(llm_client)
        self.request_timeout_seconds = request_timeout_seconds

    def create_welcome_session(
        self,
        welcome_messages: list[str],
    ) -> ConversationState:
        state = self.session_store.get_or_create(None)
        self._align_initial_stage(state)
        messages = [message.strip() for message in welcome_messages if message.strip()]

        if self.repository is not None:
            self.repository.save_state(state)
            self.repository.commit()
            turn_id = self.create_turn(
                state.session_id,
                trigger_type="welcome",
                input_text="\n".join(messages),
                status="sent",
            ) if messages else ""
            for message in messages:
                self.repository.save_message(
                    state.session_id,
                    "assistant",
                    message,
                    sender_type="salesagent",
                    customer_id=state.customer_id,
                    turn_id=turn_id,
                )
                _append_history_line(state, "assistant", "salesagent", message)
            if turn_id:
                self.repository.update_turn(
                    turn_id,
                    status="sent",
                    reply_text="\n".join(messages),
                    completed=True,
                )
            state.touch()
            self.repository.save_state(state)
            if messages:
                self.repository.schedule_followup_after_sales_message(
                    state,
                    turn_id=turn_id,
                )
            self.repository.commit()
        else:
            for message in messages:
                _append_history_line(state, "assistant", "salesagent", message)
            state.touch()

        return state.model_copy(deep=True)

    def create_turn(
        self,
        session_id: str,
        *,
        trigger_type: str,
        input_text: str = "",
        client_message_ids: list[str] | None = None,
        parent_turn_id: str = "",
        status: str = "running",
    ) -> str:
        if self.repository is None:
            return str(uuid4())
        turn = self.repository.create_turn(
            session_id,
            trigger_type=trigger_type,
            input_text=input_text,
            client_message_ids=client_message_ids,
            parent_turn_id=parent_turn_id,
            status=status,
        )
        self.repository.commit()
        return turn.turn_id

    async def process_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        client_message_id: str | None = None,
        turn_id: str | None = None,
        include_llm_call_details: bool = False,
    ) -> GraphChatTurnResult:
        state = self.session_store.get_or_create(session_id)
        self._align_initial_stage(state)
        if turn_id is None:
            if self.repository is not None:
                self.repository.save_state(state)
                self.repository.commit()
            turn_id = self.create_turn(
                state.session_id,
                trigger_type="customer_auto",
                input_text=message,
                client_message_ids=[client_message_id] if client_message_id else [],
            )
        if self.repository is not None:
            self.repository.save_state(state)
            saved_customer_message_id = self.repository.save_message(
                state.session_id,
                "user",
                message,
                sender_type="customer",
                client_message_id=client_message_id,
                customer_id=state.customer_id,
                turn_id=turn_id,
            )
            if saved_customer_message_id:
                self.repository.note_customer_message_for_sop(state)
            self.repository.commit()

        thread_id = _checkpoint_thread_id(state.session_id, client_message_id)
        try:
            result: SalesGraphState = await asyncio.wait_for(
                self.graph.ainvoke(
                    _pack_graph_state(state, message, turn_id=turn_id),
                    config=_graph_config(thread_id),
                ),
                timeout=self.request_timeout_seconds,
            )
            final_state = _unpack_graph_state(result)
            reply = str(result.get("reply") or "")
            runs = result.get("runs", [])
            final_state = _apply_sop_stage_from_runs(final_state, runs)
            sent_reply = bool(result.get("sent_reply"))
        except TimeoutError:
            final_state, reply, runs = self._fallback_result(
                state=state,
                message=message,
                action="timeout",
                reason="服务响应超时，建议人工跟进",
                elapsed_ms=int(self.request_timeout_seconds * 1000),
                error_message=f"Chat request timed out after {self.request_timeout_seconds:g}s.",
            )
            sent_reply = False
        except LLMProviderError as exc:
            failed_runs = _agent_provider_error_runs(exc)
            final_state, reply, runs = self._fallback_result(
                state=state,
                message=message,
                action="model_provider_error",
                reason="模型服务调用失败，建议人工跟进",
                elapsed_ms=0,
                error_message="模型服务暂时不可用，已转人工处理。",
                raw_output=str(exc),
            )
            runs = failed_runs + runs
            sent_reply = False

        if self.repository is not None:
            stored_state = self.repository.get_state(
                final_state.session_id,
                refresh=True,
            )
            if (
                stored_state is not None
                and stored_state.transfer_flag
                and not final_state.transfer_flag
            ):
                self.repository.save_node_invocations(final_state.session_id, runs, turn_id=turn_id)
                self.repository.update_turn(
                    turn_id,
                    status="handover",
                    reply_text="",
                    completed=True,
                )
                self.repository.save_state(stored_state)
                self.repository.cancel_pending_followups(
                    stored_state.session_id,
                    "handover",
                )
                self.repository.commit()
                stored_state = self.session_store.save(stored_state)
                return GraphChatTurnResult(
                    reply="",
                    state=stored_state,
                    agent_runs=[
                        serialize_run(
                            run,
                            include_llm_call_details=include_llm_call_details,
                        )
                        for run in runs
                    ],
                )
            if reply and sent_reply:
                saved_reply_message_id = self.repository.save_message(
                    final_state.session_id,
                    "assistant",
                    reply,
                    sender_type="salesagent",
                    customer_id=final_state.customer_id,
                    turn_id=turn_id,
                )
                if saved_reply_message_id:
                    self.repository.schedule_followup_after_sales_message(
                        final_state,
                        turn_id=turn_id,
                    )
            elif final_state.transfer_flag:
                self.repository.cancel_pending_followups(
                    final_state.session_id,
                    "handover",
                )
            self.repository.save_node_invocations(final_state.session_id, runs, turn_id=turn_id)
            self.repository.save_session_state(final_state)
            self.repository.save_customer_profile(final_state)
            self.repository.save_memory(final_state, turn_id=turn_id)
            self.repository.update_turn(
                turn_id,
                status="sent" if reply and sent_reply else ("handover" if final_state.transfer_flag else "completed"),
                reply_text=reply,
                completed=True,
            )
            self.repository.commit()

        final_state = self.session_store.save(final_state)

        return GraphChatTurnResult(
            reply=reply,
            state=final_state,
            agent_runs=[
                serialize_run(
                    run,
                    include_llm_call_details=include_llm_call_details,
                )
                for run in runs
            ],
        )

    async def stream_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        client_message_id: str | None = None,
        turn_id: str | None = None,
        persist_user_message: bool = True,
        persist_reply_message: bool = True,
        fallback_on_cancel: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run the LangGraph workflow and yield compact, frontend-friendly events."""
        state = self.session_store.get_or_create(session_id)
        self._align_initial_stage(state)
        if turn_id is None:
            if self.repository is not None:
                self.repository.save_state(state)
                self.repository.commit()
            turn_id = self.create_turn(
                state.session_id,
                trigger_type="customer_auto",
                input_text=message,
                client_message_ids=[client_message_id] if client_message_id else [],
            )
        if self.repository is not None and persist_user_message:
            self.repository.save_state(state)
            saved_customer_message_id = self.repository.save_message(
                state.session_id,
                "user",
                message,
                sender_type="customer",
                client_message_id=client_message_id,
                customer_id=state.customer_id,
                turn_id=turn_id,
            )
            if saved_customer_message_id:
                self.repository.note_customer_message_for_sop(state)
            self.repository.commit()

        graph_state: SalesGraphState = _pack_graph_state(state, message, turn_id=turn_id)
        thread_id = _checkpoint_thread_id(state.session_id, client_message_id)
        final_state = state
        reply = ""
        runs: list[AgentRunResult] = []
        saved_runs_count = 0
        interrupted = False
        reply_message_saved = False

        def persist_progress(current_state: ConversationState, node_name: str) -> None:
            nonlocal saved_runs_count
            if self.repository is None:
                return
            new_runs = runs[saved_runs_count:]
            if new_runs:
                self.repository.save_node_invocations(current_state.session_id, new_runs, turn_id=turn_id)
                saved_runs_count = len(runs)
            if node_name == "memory_update":
                self.repository.save_customer_profile(current_state)
                self.repository.save_memory(current_state, turn_id=turn_id)
            else:
                self.repository.save_session_state(current_state)
            self.repository.commit()

        def persist_reply_message_to_db(
            current_state: ConversationState,
            current_reply: str,
        ) -> None:
            nonlocal reply_message_saved
            if (
                self.repository is None
                or not persist_reply_message
                or reply_message_saved
                or not current_reply
            ):
                return
            saved_reply_message_id = self.repository.save_message(
                current_state.session_id,
                "assistant",
                current_reply,
                sender_type="salesagent",
                customer_id=current_state.customer_id,
                turn_id=turn_id,
            )
            if saved_reply_message_id:
                self.repository.schedule_followup_after_sales_message(
                    current_state,
                    turn_id=turn_id,
                )
            reply_message_saved = True

        stream_task = asyncio.current_task()
        if stream_task is not None:
            self._register_active_stream(state.session_id, stream_task)
        try:
            yield {
                "type": "session",
                "session_id": state.session_id,
                "state": _serialize_state(state),
            }
            yield self._status_event("init")

            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    async for update in self.graph.astream(
                        graph_state,
                        config=_graph_config(thread_id),
                        stream_mode="updates",
                    ):
                        if (
                            not final_state.transfer_flag
                            and self._handover_enabled(state.session_id)
                        ):
                            interrupted = True
                            final_state = self._latest_state(final_state)
                            break
                        if not isinstance(update, dict):
                            continue
                        for node_name, node_update in update.items():
                            if (
                                not final_state.transfer_flag
                                and self._handover_enabled(state.session_id)
                            ):
                                interrupted = True
                                final_state = self._latest_state(final_state)
                                break
                            if not isinstance(node_update, dict):
                                continue

                            node_runs = list(node_update.get("runs") or [])
                            runs.extend(node_runs)

                            for key, value in node_update.items():
                                if key == "runs":
                                    continue
                                graph_state[key] = value

                            # 从顶层字段重建 ConversationState
                            final_state = _unpack_graph_state(graph_state)
                            if "reply" in node_update:
                                reply = str(node_update.get("reply") or "")

                            if (
                                node_name == "send"
                                and persist_reply_message
                                and self.repository is not None
                                and not reply_message_saved
                                and reply
                                and bool(graph_state.get("sent_reply"))
                            ):
                                saved_reply_message_id = self.repository.save_message(
                                    final_state.session_id,
                                    "assistant",
                                    reply,
                                    sender_type="salesagent",
                                    customer_id=final_state.customer_id,
                                    turn_id=turn_id,
                                )
                                if saved_reply_message_id:
                                    self.repository.schedule_followup_after_sales_message(
                                        final_state,
                                        turn_id=turn_id,
                                    )
                                reply_message_saved = True

                            persist_progress(final_state, node_name)

                            next_node = _next_node_name(node_name, graph_state)
                            next_status = (
                                NODE_RUNNING_STATUS.get(next_node, "")
                                if next_node
                                else ""
                            )
                            yield {
                                "type": "node_complete",
                                "node": node_name,
                                "node_label": NODE_LABELS.get(node_name, node_name),
                                "status": f"已完成：{NODE_LABELS.get(node_name, node_name)}",
                                "next_node": next_node,
                                "next_status": next_status,
                                "state": _serialize_state(final_state),
                                "graph": _serialize_graph_snapshot(graph_state),
                                "runs": [serialize_run(run) for run in node_runs],
                                "completed_runs": len(runs),
                            }
                            if next_node:
                                yield self._status_event(next_node)
                        if interrupted:
                            break
            except asyncio.CancelledError:
                if self._handover_enabled(state.session_id):
                    interrupted = True
                    final_state = self._latest_state(final_state)
                elif not fallback_on_cancel:
                    yield {
                        "type": "final",
                        "session_id": final_state.session_id,
                        "reply": "",
                        "state": _serialize_state(final_state),
                        "agent_runs": [serialize_run(run) for run in runs],
                        "status": "已被新客户消息合并重跑",
                        "interrupted": True,
                        "cancelled_for_restart": True,
                    }
                    raise
                else:
                    final_state, reply, fallback_runs = self._fallback_result(
                        state=final_state,
                        message=message,
                        action="request_cancelled",
                        reason="请求被中断，建议人工跟进",
                        elapsed_ms=0,
                        error_message="请求被取消，已转人工处理。",
                    )
                    runs.extend(fallback_runs)
                    graph_state["sent_reply"] = False
                    graph_state["reply"] = reply
                    persist_reply_message_to_db(final_state, reply)
                    persist_progress(final_state, "finalize")
                    return
            except TimeoutError:
                final_state, reply, fallback_runs = self._fallback_result(
                    state=final_state,
                    message=message,
                    action="timeout",
                    reason="服务响应超时，建议人工跟进",
                    elapsed_ms=int(self.request_timeout_seconds * 1000),
                    error_message=(
                        f"Chat request timed out after "
                        f"{self.request_timeout_seconds:g}s."
                    ),
                )
                runs.extend(fallback_runs)
                graph_state["sent_reply"] = False
                graph_state["reply"] = reply
                persist_reply_message_to_db(final_state, reply)
                persist_progress(final_state, "finalize")
                yield self._fallback_event(
                    final_state,
                    reply,
                    fallback_runs,
                    "请求超时，已转人工处理",
                )
            except LLMProviderError as exc:
                failed_runs = _agent_provider_error_runs(exc)
                final_state, reply, fallback_runs = self._fallback_result(
                    state=final_state,
                    message=message,
                    action="model_provider_error",
                    reason="模型服务调用失败，建议人工跟进",
                    elapsed_ms=0,
                    error_message="模型服务暂时不可用，已转人工处理。",
                    raw_output=str(exc),
                )
                runs.extend(failed_runs)
                runs.extend(fallback_runs)
                graph_state["sent_reply"] = False
                graph_state["reply"] = reply
                persist_reply_message_to_db(final_state, reply)
                persist_progress(final_state, "finalize")
                yield self._fallback_event(
                    final_state,
                    reply,
                    fallback_runs,
                    "模型服务异常，已转人工处理",
                )
            except Exception as exc:
                final_state, reply, fallback_runs = self._fallback_result(
                    state=final_state,
                    message=message,
                    action="graph_error",
                    reason="服务运行异常，建议人工跟进",
                    elapsed_ms=0,
                    error_message="服务运行异常，已转人工处理。",
                    raw_output=repr(exc),
                )
                runs.extend(fallback_runs)
                graph_state["sent_reply"] = False
                graph_state["reply"] = reply
                persist_reply_message_to_db(final_state, reply)
                persist_progress(final_state, "finalize")
                yield self._fallback_event(
                    final_state,
                    reply,
                    fallback_runs,
                    "服务异常，已转人工处理",
                )

            if (
                not final_state.transfer_flag
                and self._handover_enabled(final_state.session_id)
            ):
                interrupted = True

            if interrupted:
                final_state = self._latest_state(final_state)
                persist_progress(final_state, "finalize")
                yield {
                    "type": "final",
                    "session_id": final_state.session_id,
                    "reply": "",
                    "state": _serialize_state(final_state),
                    "agent_runs": [serialize_run(run) for run in runs],
                    "status": "已转人工接管，自动回复已中断",
                    "interrupted": True,
                }
                return

            if self.repository is not None:
                if (
                    reply
                    and persist_reply_message
                    and bool(graph_state.get("sent_reply"))
                    and not reply_message_saved
                ):
                    saved_reply_message_id = self.repository.save_message(
                        final_state.session_id,
                        "assistant",
                        reply,
                        sender_type="salesagent",
                        customer_id=final_state.customer_id,
                        turn_id=turn_id,
                    )
                    if saved_reply_message_id:
                        self.repository.schedule_followup_after_sales_message(
                            final_state,
                            turn_id=turn_id,
                        )
                new_runs = runs[saved_runs_count:]
                if new_runs:
                    self.repository.save_node_invocations(final_state.session_id, new_runs, turn_id=turn_id)
                self.repository.save_session_state(final_state)
                self.repository.save_customer_profile(final_state)
                self.repository.save_memory(final_state, turn_id=turn_id)
                self.repository.update_turn(
                    turn_id,
                    status="sent" if reply and bool(graph_state.get("sent_reply")) else ("handover" if final_state.transfer_flag else "completed"),
                    reply_text=reply,
                    completed=True,
                )
                self.repository.commit()

            yield {
                "type": "final",
                "session_id": final_state.session_id,
                "turn_id": turn_id,
                "reply": reply,
                "state": _serialize_state(final_state),
                "agent_runs": [serialize_run(run) for run in runs],
                "status": "处理完成",
            }
        finally:
            if stream_task is not None:
                self._clear_active_stream(state.session_id, stream_task)

    def persist_human_message(
        self,
        session_id: str,
        content: str,
        *,
        client_message_id: str | None = None,
        turn_id: str | None = None,
    ) -> ConversationState:
        return self.persist_messages(
            session_id,
            [
                {
                    "role": "assistant",
                    "sender_type": "human",
                    "content": content,
                    "client_message_id": client_message_id,
                }
            ],
            turn_id=turn_id,
            trigger_type="human_reply",
        )

    def persist_customer_message(
        self,
        session_id: str | None,
        content: str,
        *,
        client_message_id: str | None = None,
        turn_id: str | None = None,
    ) -> ConversationState:
        """保存客户消息并返回会话状态，不触发自动回复流程。"""
        state = self.session_store.get_or_create(session_id)
        self._align_initial_stage(state)
        if self.repository is not None:
            self.repository.save_state(state)
            saved_customer_message_id = self.repository.save_message(
                state.session_id,
                "user",
                content,
                sender_type="customer",
                client_message_id=client_message_id,
                customer_id=state.customer_id,
                turn_id=turn_id,
            )
            if saved_customer_message_id:
                self.repository.note_customer_message_for_sop(state)
            self.repository.commit()
        return state

    async def update_memory_for_exchange(
        self,
        session_id: str,
        *,
        customer_message: str,
        reply: str,
        graph: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> GraphStateResult | None:
        """在客户可见回复发送后异步更新画像和压缩记忆。"""
        if not reply.strip():
            return None
        state = self.session_store.get_or_create(session_id)
        graph = graph or {}
        run = await self.memory_agent.run(
            {
                "current_memory": state.history_summary,
                "new_exchange": {
                    "customer": customer_message,
                    "salesagent": reply,
                },
                "message": customer_message,
                "reply": reply,
                "intent": graph.get("intent", {}),
                "sop": graph.get("sop", {}),
                "knowledge": graph.get("knowledge_output", {}),
                "safety": graph.get("safety", {}),
                "current_profile": state.customer_profile.model_dump(),
                "current_stage": state.current_stage,
                "source": "async_after_send",
            }
        )
        output = _as_dict(run.output)
        state.customer_profile = _apply_profile_update(state.customer_profile, output)
        state.history_summary = _extract_memory_summary(
            output,
            old_summary=state.history_summary,
            message=customer_message,
            reply=reply,
        )
        state.touch()
        if self.repository is not None:
            self.repository.save_node_invocations(state.session_id, [run], turn_id=turn_id)
            self.repository.save_customer_profile(state)
            self.repository.save_memory(state, turn_id=turn_id)
            self.repository.commit()
        return GraphStateResult(
            state=state,
            agent_runs=[serialize_run(run)],
        )

    def reset_session(self, session_id: str) -> ConversationState:
        state = self.session_store.reset(session_id)
        self._align_initial_stage(state)
        if self.repository is not None:
            self.repository.save_state(state)
            self.repository.commit()
        return state

    def _align_initial_stage(self, state: ConversationState) -> None:
        if state.message_count != 0:
            return
        stage_options = self.knowledge_loader.list_sop_stages(include_terminal=False)
        if stage_options and state.current_stage not in stage_options:
            state.current_stage = stage_options[0]

    async def set_handover(
        self,
        session_id: str,
        *,
        enabled: bool,
        reason: str = "",
    ) -> GraphStateResult:
        state = self.session_store.get_or_create(session_id)
        runs: list[AgentRunResult] = []

        if not enabled and state.transfer_flag:
            catch_up_run = await self._run_memory_catch_up(state)
            if catch_up_run is not None:
                runs.append(catch_up_run)

        state.transfer_flag = enabled
        state.transfer_reason = reason if enabled else ""
        state.touch()
        if self.repository is not None:
            turn_id = (
                self.create_turn(
                    state.session_id,
                    trigger_type="handover_catch_up",
                    input_text=reason,
                    status="completed",
                )
                if runs
                else None
            )
            if runs:
                self.repository.save_node_invocations(state.session_id, runs, turn_id=turn_id)
                self.repository.update_turn(
                    turn_id or "",
                    status="completed",
                    completed=True,
                )
            self.repository.save_state(state)
            if enabled:
                self.repository.cancel_pending_followups(state.session_id, "handover")
            self.repository.commit()
        if enabled:
            self._cancel_active_stream(state.session_id)
        return GraphStateResult(
            state=state.model_copy(deep=True),
            agent_runs=[serialize_run(run) for run in runs],
        )

    def list_session_snapshots(
        self,
        *,
        limit: int = 50,
        include_internal: bool = True,
        viewer_type: str = "sales",
    ) -> list[dict[str, Any]]:
        if self.repository is None:
            return []

        sessions = self.repository.list_sessions(limit=limit)
        stage_options = self.knowledge_loader.list_sop_stages(include_terminal=False)
        return [
            self._build_session_snapshot(
                session.session_id,
                session,
                include_detail=False,
                include_internal=include_internal,
                viewer_type=viewer_type,
                stage_options=stage_options,
            )
            for session in sessions
        ]

    def get_session_snapshot(
        self,
        session_id: str,
        *,
        include_internal: bool = True,
        viewer_type: str = "sales",
    ) -> dict[str, Any] | None:
        if self.repository is None:
            return None
        state = self.repository.get_state(session_id)
        messages = self.repository.list_messages(session_id)
        if state is None and not messages:
            return None
        return self._build_session_snapshot(
            session_id,
            include_detail=True,
            include_internal=include_internal,
            viewer_type=viewer_type,
        )

    def mark_session_read(
        self,
        session_id: str,
        *,
        viewer_type: str,
        include_internal: bool,
    ) -> dict[str, Any] | None:
        if self.repository is None:
            return None

        messages = self.repository.list_messages(session_id)
        visible_messages = _visible_messages(messages, include_internal)
        if not messages and self.repository.get_state(session_id) is None:
            return None
        if visible_messages:
            self.repository.save_read_cursor(
                session_id,
                viewer_type,
                visible_messages[-1],
            )
            self.repository.commit()
        return self._build_session_snapshot(
            session_id,
            include_detail=True,
            include_internal=include_internal,
            viewer_type=viewer_type,
        )

    def _build_session_snapshot(
        self,
        session_id: str,
        session_record: Any | None = None,
        *,
        include_detail: bool,
        include_internal: bool,
        viewer_type: str,
        stage_options: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.repository is None:
            return {}

        if session_record is None:
            session_record = self.repository.get_session_record(session_id)
        messages = self.repository.list_messages(session_id)
        visible_messages = _visible_messages(messages, include_internal)
        node_invocations = (
            self.repository.list_node_invocations(session_id)
            if include_detail and include_internal
            else []
        )
        llm_calls = (
            self.repository.list_llm_calls(session_id)
            if include_detail and include_internal
            else []
        )
        state = self.repository.get_state(session_id)
        sop_state = self.repository.get_sop_state(session_id)
        graph_status = (
            _graph_status_from_runs(node_invocations)
            if include_detail and include_internal
            else None
        )
        is_processing = (
            include_detail
            and include_internal
            and _looks_like_processing(visible_messages, state)
        )
        processing_status = ""
        if is_processing and graph_status is not None:
            processing_status = (
                graph_status.get("status", "正在处理客户消息")
                if graph_status.get("completed_runs", 0) > 0
                else NODE_RUNNING_STATUS["init"]
            )
        latest_message = visible_messages[-1] if visible_messages else None
        read_cursor = self.repository.get_read_cursor(session_id, viewer_type)
        unread_count = _unread_count(visible_messages, read_cursor, viewer_type)
        read_cursor_message_id = (
            getattr(read_cursor, "last_read_message_id", "") if read_cursor else ""
        )
        read_cursor_at = getattr(read_cursor, "last_read_at", None) if read_cursor else None

        return {
            "session_id": session_id,
            "customer_id": getattr(session_record, "customer_id", "")
            or getattr(state, "customer_id", ""),
            "sales_id": getattr(session_record, "sales_id", ""),
            "sales_name": getattr(session_record, "sales_name", ""),
            "preview": _session_preview(visible_messages),
            "persisted": True,
            "messages": [
                {
                    "id": message.client_message_id or message.message_id,
                    "role": message.role,
                    "text": message.content,
                    "sender_type": (
                        message.sender_type
                        or _default_sender_type_for_role(message.role)
                    ),
                    "turn_id": getattr(message, "turn_id", ""),
                    "customer_id": getattr(message, "customer_id", ""),
                    "sales_id": getattr(message, "sales_id", ""),
                    "sales_name": getattr(message, "sales_name", ""),
                    "client_message_id": message.client_message_id or "",
                    "created_at": _beijing_time(getattr(message, "created_at", None)),
                }
                for message in visible_messages
            ] if include_detail else [],
            "state": state.model_dump(mode="json") if state is not None else None,
            "agent_runs": [_serialize_stored_run(run) for run in node_invocations],
            "llm_calls": [_serialize_llm_call(call) for call in llm_calls],
            "stage_options": stage_options
            if stage_options is not None
            else self.knowledge_loader.list_sop_stages(include_terminal=False),
            "graph_status": graph_status,
            "detail_loaded": include_detail,
            "isProcessing": is_processing,
            "processingStatus": processing_status,
            "latest_message_id": _message_identity(latest_message),
            "latest_sender_type": (
                getattr(latest_message, "sender_type", "") if latest_message else ""
            ),
            "latest_message_at": (
                _beijing_time(getattr(latest_message, "created_at", None)) if latest_message else None
            ),
            "message_count": len(visible_messages),
            "has_unread": unread_count > 0,
            "unread_count": unread_count,
            "read_cursor_message_id": read_cursor_message_id,
            "read_cursor_at": _beijing_time(read_cursor_at),
            "reply_mode": "human" if bool(state and state.transfer_flag) else "ai",
            "sop_followup": _serialize_sop_followup(sop_state),
            "created_at": _beijing_time(getattr(session_record, "created_at", None)),
            "updated_at": _beijing_time(getattr(session_record, "updated_at", None)),
        }

    def persist_messages(
        self,
        session_id: str | None,
        messages: list[dict[str, Any]],
        *,
        turn_id: str | None = None,
        trigger_type: str = "manual",
    ) -> ConversationState:
        state = self.session_store.get_or_create(session_id)
        self._align_initial_stage(state)
        non_empty_messages = [
            message
            for message in messages
            if str(message.get("content") or "").strip()
        ]
        if turn_id is None and non_empty_messages:
            if self.repository is not None:
                self.repository.save_state(state)
                self.repository.commit()
            input_text = "\n".join(
                str(message.get("content") or "").strip()
                for message in non_empty_messages
            )
            client_message_ids = [
                str(message.get("client_message_id") or "")
                for message in non_empty_messages
                if str(message.get("client_message_id") or "")
            ]
            turn_id = self.create_turn(
                state.session_id,
                trigger_type=trigger_type,
                input_text=input_text,
                client_message_ids=client_message_ids,
                status="completed",
            )
        reply_texts: list[str] = []
        for message in messages:
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            role = str(message.get("role") or "user")
            sender_type = str(
                message.get("sender_type")
                or _default_sender_type_for_role(role)
            )
            client_message_id = str(message.get("client_message_id") or "")
            should_update_history = True
            if self.repository is not None:
                should_update_history = self.repository.save_message(
                    state.session_id,
                    role,
                    content,
                    sender_type=sender_type,
                    client_message_id=client_message_id or None,
                    customer_id=state.customer_id,
                    turn_id=turn_id,
                )
            if should_update_history:
                _append_history_line(state, role, sender_type, content)
                if self.repository is not None and sender_type == "customer":
                    self.repository.note_customer_message_for_sop(state)
            if sender_type in {"salesagent", "human"} or role == "assistant":
                reply_texts.append(content)

        state.touch()
        if self.repository is not None:
            self.repository.save_state(state)
            if reply_texts:
                self.repository.schedule_followup_after_sales_message(
                    state,
                    turn_id=turn_id,
                )
            if turn_id:
                self.repository.update_turn(
                    turn_id,
                    status="sent" if reply_texts else "completed",
                    reply_text="\n".join(reply_texts),
                    completed=True,
                )
            self.repository.commit()
        return state

    def _status_event(self, node_name: str) -> dict[str, Any]:
        return {
            "type": "status",
            "node": node_name,
            "node_label": NODE_LABELS.get(node_name, node_name),
            "status": NODE_RUNNING_STATUS.get(node_name, node_name),
        }

    def _register_active_stream(
        self,
        session_id: str,
        task: asyncio.Task[Any],
    ) -> None:
        previous = _ACTIVE_STREAM_TASKS.get(session_id)
        if previous is not None and previous is not task and not previous.done():
            previous.cancel()
        _ACTIVE_STREAM_TASKS[session_id] = task

    def _clear_active_stream(
        self,
        session_id: str,
        task: asyncio.Task[Any],
    ) -> None:
        if _ACTIVE_STREAM_TASKS.get(session_id) is task:
            _ACTIVE_STREAM_TASKS.pop(session_id, None)

    def _cancel_active_stream(self, session_id: str) -> None:
        task = _ACTIVE_STREAM_TASKS.get(session_id)
        if task is not None and not task.done():
            task.cancel()

    def _handover_enabled(self, session_id: str) -> bool:
        if self.repository is None:
            return False
        state = self.repository.get_state(session_id, refresh=True)
        return bool(state and state.transfer_flag)

    def _latest_state(self, fallback_state: ConversationState) -> ConversationState:
        if self.repository is None:
            return fallback_state
        return self.repository.get_state(
            fallback_state.session_id,
            refresh=True,
        ) or fallback_state

    async def _run_memory_catch_up(
        self,
        state: ConversationState,
    ) -> AgentRunResult | None:
        manual_context = self._build_manual_context(state)
        if not manual_context:
            return None

        try:
            run = await asyncio.wait_for(
                self.memory_agent.run(
                    {
                        "message": manual_context,
                        "current_profile": state.customer_profile.model_dump(),
                        "source": "handover_catch_up",
                    }
                ),
                timeout=self.request_timeout_seconds,
            )
        except Exception as exc:
            return AgentRunResult(
                agent_name="memory_agent",
                output={"action": "memory_catch_up_failed"},
                raw_output=repr(exc),
                input_payload={
                    "session_id": state.session_id,
                    "source": "handover_catch_up",
                },
                elapsed_ms=0,
                provider="system",
                model="memory_catch_up",
                success=False,
                error_message="人工接管记录画像补录失败，已保留原始聊天上下文。",
            )

        if isinstance(run.output, dict):
            updated_profile = _apply_profile_update(state.customer_profile, run.output)
            state.customer_profile = updated_profile
        return run

    def _build_manual_context(self, state: ConversationState) -> str:
        if self.repository is not None:
            messages = self._handover_context_messages(state)
            return "\n".join(
                f"{_handover_speaker(message)}：{message.content.strip()}"
                for message in messages
                if message.content.strip()
            )

        return "\n".join(
            line
            for line in state.history_summary.splitlines()
            if line.startswith(("客户：", "人工："))
        )

    def _handover_context_messages(self, state: ConversationState) -> list[Any]:
        if self.repository is None:
            return []

        messages = self.repository.list_messages(state.session_id)
        start = self._handover_context_start_message(state)
        if start is not None:
            start_id = _message_identity(start)
            for index, message in enumerate(messages):
                if _message_identity(message) == start_id:
                    return [
                        item
                        for item in messages[index:]
                        if _is_handover_context_message(item, None)
                    ]
        return [
            message
            for message in messages
            if _is_handover_context_message(message, None)
        ]

    def _handover_context_start_message(self, state: ConversationState) -> Any | None:
        if self.repository is None:
            return None
        messages = self.repository.list_messages(state.session_id)
        # 只查找 salesagent 消息作为分界点（human 消息是转人工的一部分，不应作为边界）
        last_sales_index = -1
        for index, message in enumerate(messages):
            if getattr(message, "sender_type", "") == "salesagent":
                last_sales_index = index
        for message in messages[last_sales_index + 1:]:
            if getattr(message, "sender_type", "") == "customer":
                return message
        for message in reversed(messages):
            if getattr(message, "sender_type", "") == "customer":
                return message
        return None

    def _fallback_event(
        self,
        state: ConversationState,
        reply: str,
        runs: list[AgentRunResult],
        status_text: str,
    ) -> dict[str, Any]:
        return {
            "type": "node_complete",
            "node": "sales_graph",
            "node_label": NODE_LABELS["sales_graph"],
            "status": status_text,
            "next_node": None,
            "next_status": "",
            "state": _serialize_state(state),
            "graph": {"reply": reply},
            "runs": [serialize_run(run) for run in runs],
            "completed_runs": len(runs),
        }

    def _fallback_result(
        self,
        *,
        state: ConversationState,
        message: str,
        action: str,
        reason: str,
        elapsed_ms: int,
        error_message: str,
        raw_output: str = "",
    ) -> tuple[ConversationState, str, list[AgentRunResult]]:
        state.transfer_flag = True
        state.transfer_reason = reason
        state.touch()
        reply = ""
        runs = [
            AgentRunResult(
                agent_name="sales_graph",
                output={"action": action},
                raw_output=raw_output,
                input_payload={"message": message, "session_id": state.session_id},
                elapsed_ms=elapsed_ms,
                provider="system",
                model="fallback",
                success=False,
                error_message=error_message,
            )
        ]
        return state, reply, runs


def _agent_provider_error_runs(exc: LLMProviderError) -> list[AgentRunResult]:
    agent_name = str(getattr(exc, "agent_name", "") or "")
    if not agent_name:
        return []
    return [
        AgentRunResult(
            agent_name=agent_name,
            output={"_agent_error": "llm_provider_error"},
            raw_output=str(exc),
            input_payload=getattr(exc, "input_payload", {}),
            elapsed_ms=int(getattr(exc, "elapsed_ms", 0) or 0),
            provider="llm_fallback",
            model="all_attempts_failed",
            success=False,
            error_message=str(exc),
            llm_call_attempts=list(getattr(exc, "call_attempts", []) or []),
        )
    ]


def _next_node_name(node_name: str, graph_state: SalesGraphState) -> str | None:
    static_next = {
        "init": "supervisor_router",
        "sop": "context_gate",
        "knowledge": "context_gate",
        "sales_case_rag": "context_gate",
        "conversation": "safety",
        "rewrite_reply": "safety",
        "handover": "finalize",
        "final_reply": "send",
        "send": "finalize + memory_update",
    }
    if node_name == "supervisor_router":
        return route_after_supervisor(graph_state)
    if node_name == "intent":
        route = route_after_intent(graph_state)
        if isinstance(route, list):
            return " + ".join(route)
        return route
    if node_name == "context_gate":
        return route_after_knowledge(graph_state)
    if node_name == "safety":
        route = route_after_safety(graph_state)
        return "rewrite_reply" if route == "rewrite" else route
    if node_name in {"finalize", "memory_update"}:
        return None
    return static_next.get(node_name)


def _checkpoint_thread_id(session_id: str, client_message_id: str | None) -> str:
    turn_id = client_message_id or f"server-{uuid4()}"
    return f"{session_id}:{turn_id}"


def _graph_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _serialize_state(state: ConversationState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _serialize_graph_snapshot(graph_state: SalesGraphState) -> dict[str, Any]:
    keys = (
        "supervisor",
        "intent",
        "sop",
        "knowledge_output",
        "knowledge_sufficiency",
        "draft_reply",
        "safety",
        "reply",
        "sent_reply",
    )
    return {
        key: graph_state[key]
        for key in keys
        if key in graph_state and graph_state[key] not in (None, "", [], {})
    }


def _session_preview(messages: list[Any]) -> str:
    for message in reversed(messages):
        content = str(getattr(message, "content", "") or "").strip()
        if content:
            return content
    return ""


def _visible_messages(messages: list[Any], include_internal: bool) -> list[Any]:
    if include_internal:
        return messages
    return [
        message
        for message in messages
        if getattr(message, "sender_type", "") in {"customer", "salesagent", "human"}
    ]


def _unread_count(
    messages: list[Any],
    read_cursor: Any | None,
    viewer_type: str,
) -> int:
    incoming_sender_types = _incoming_sender_types(viewer_type)
    return sum(
        1
        for message in messages
        if getattr(message, "sender_type", "") in incoming_sender_types
        and _is_after_read_cursor(message, read_cursor)
    )


def _incoming_sender_types(viewer_type: str) -> set[str]:
    if viewer_type == "customer":
        return {"salesagent", "human"}
    return {"customer"}


def _is_after_read_cursor(message: Any, read_cursor: Any | None) -> bool:
    if read_cursor is None or getattr(read_cursor, "last_read_at", None) is None:
        return True
    created_at = getattr(message, "created_at", None)
    if not isinstance(created_at, datetime):
        return True
    return _as_utc_time(created_at) > _as_utc_time(read_cursor.last_read_at)


def _message_identity(message: Any | None) -> str:
    if message is None:
        return ""
    return str(
        getattr(message, "client_message_id", "")
        or getattr(message, "message_id", "")
        or "",
    )


def _graph_status_from_runs(runs: list[Any]) -> dict[str, Any]:
    if not runs:
        return {
            "node": "init",
            "node_label": NODE_LABELS["init"],
            "status": "等待客户消息",
            "completed_runs": 0,
        }

    last_run = runs[-1]
    node_name = getattr(last_run, "node_name", "") or AGENT_NODE_BY_RUN.get(
        getattr(last_run, "agent_name", ""), "finalize",
    )
    node_label = NODE_LABELS.get(node_name, node_name)
    status = (
        f"最近完成：{node_label}"
        if bool(last_run.success)
        else f"最近失败：{node_label}"
    )
    return {
        "node": node_name,
        "node_label": node_label,
        "status": status,
        "completed_runs": len(runs),
    }


def _looks_like_processing(
    messages: list[Any],
    state: ConversationState | None,
) -> bool:
    if not messages or (state is not None and state.transfer_flag):
        return False
    latest = messages[-1]
    return getattr(latest, "sender_type", "") == "customer"


def _serialize_stored_run(run: Any) -> dict[str, Any]:
    return {
        "id": getattr(run, "invocation_id", getattr(run, "agent_run_id", "")),
        "turn_id": getattr(run, "turn_id", ""),
        "agent_name": getattr(run, "node_name", getattr(run, "agent_name", "")),
        "provider": run.model_provider,
        "model": run.model_name,
        "elapsed_ms": run.elapsed_ms,
        "success": bool(run.success),
        "error_message": run.error_message or "",
        "input_payload": _json_loads(run.input_json, {}),
        "output": _json_loads(run.output_json, {}),
        "created_at": _beijing_time(getattr(run, "created_at", None)),
    }


def _serialize_llm_call(call: Any) -> dict[str, Any]:
    return {
        "id": call.call_id,
        "turn_id": getattr(call, "turn_id", ""),
        "node_invocation_id": call.node_invocation_id,
        "node_name": call.node_name,
        "provider": call.provider,
        "model": call.model_name,
        "api_url": call.api_url,
        "protocol": call.protocol,
        "attempt_index": call.attempt_index,
        "elapsed_ms": call.elapsed_ms,
        "success": bool(call.success),
        "error_type": call.error_type or "",
        "error_message": call.error_message or "",
        "request_payload": _json_loads(call.request_json, {}),
        "response": _json_loads(call.response_json, {}),
        "usage": _json_loads(call.usage_json, {}),
        "created_at": _beijing_time(getattr(call, "created_at", None)),
    }


def _serialize_sop_followup(sop_state: Any | None) -> dict[str, Any] | None:
    if sop_state is None:
        return None
    return {
        "current_stage": getattr(sop_state, "current_stage", ""),
        "status": getattr(sop_state, "status", ""),
        "followup_count": getattr(sop_state, "followup_count", 0),
        "next_followup_at": _beijing_time(getattr(sop_state, "next_followup_at", None)),
        "latest_job_id": getattr(sop_state, "latest_job_id", ""),
        "last_customer_message_at": _beijing_time(getattr(sop_state, "last_customer_message_at", None)),
        "last_sales_message_at": _beijing_time(getattr(sop_state, "last_sales_message_at", None)),
    }


def _json_loads(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _append_history_line(
    state: ConversationState,
    role: str,
    sender_type: str,
    content: str,
) -> None:
    speaker = _history_speaker(role, sender_type)
    state.history_summary = f"{state.history_summary}\n{speaker}：{content}\n"[-3000:]
    if role in {"user", "assistant"}:
        state.message_count += 1


def _history_speaker(role: str, sender_type: str) -> str:
    if sender_type == "human":
        return "人工"
    if sender_type == "salesagent":
        return "AI"
    if role == "user" or sender_type == "customer":
        return "客户"
    return "系统"


def _default_sender_type_for_role(role: str) -> str:
    if role == "user":
        return "customer"
    if role == "assistant":
        return "salesagent"
    return "system"


def _is_handover_context_message(
    message: Any,
    started_at: datetime | None,
) -> bool:
    sender_type = str(getattr(message, "sender_type", "") or "")
    role = str(getattr(message, "role", "") or "")
    if sender_type not in {"customer", "human"} and role != "user":
        return False
    if started_at is None:
        return True
    created_at = getattr(message, "created_at", None)
    if not isinstance(created_at, datetime):
        return True
    return _as_utc_time(created_at) >= _as_utc_time(started_at)


def _handover_speaker(message: Any) -> str:
    if getattr(message, "sender_type", "") == "human":
        return "人工"
    return "客户"


def _beijing_time(value: datetime | None) -> datetime | None:
    return to_beijing_time(value)


def _as_utc_time(value: datetime) -> datetime:
    return to_utc_time(value)
