from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.auth import verify_auth_token
from app.core.config import get_settings
from app.db import SessionLocal
from app.graph import SalesGraphService
from app.llm import create_llm_client
from app.realtime import realtime_manager
from app.repositories import ChatRepository


router = APIRouter(tags=["realtime"])
logger = logging.getLogger(__name__)

VALID_VIEWERS = {"sales", "customer"}


@dataclass(slots=True)
class PendingCustomerMessage:
    content: str
    client_message_id: str | None = None


@dataclass(slots=True)
class SessionAutoReplyState:
    pending: list[PendingCustomerMessage] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    first_reply_sent: bool = False
    generation: int = 0


_AUTO_REPLY_STATES: dict[str, SessionAutoReplyState] = {}
_MEMORY_LOCKS: dict[str, asyncio.Lock] = {}


@contextmanager
def _chat_service(*, include_memory_update: bool = True) -> Iterator[SalesGraphService]:
    db = SessionLocal()
    try:
        settings = get_settings()
        yield SalesGraphService(
            create_llm_client(settings),
            repository=ChatRepository(db),
            request_timeout_seconds=settings.chat_request_timeout_seconds,
            include_memory_update=include_memory_update,
        )
    finally:
        db.close()


@router.websocket("/ws")
async def chat_websocket(
    websocket: WebSocket,
    viewer: str = "sales",
    token: str = "",
) -> None:
    if viewer not in VALID_VIEWERS:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if viewer == "sales":
        try:
            verify_auth_token(token, required_scope="sales")
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await realtime_manager.connect(websocket, viewer)
    await realtime_manager.send_json(
        websocket,
        {"type": "connected", "viewer": viewer},
    )
    try:
        while True:
            payload = await websocket.receive_json()
            await _handle_client_event(websocket, viewer, payload)
    except WebSocketDisconnect:
        realtime_manager.disconnect(websocket, viewer)


async def _handle_client_event(
    websocket: WebSocket,
    viewer: str,
    payload: dict[str, Any],
) -> None:
    event_type = str(payload.get("type") or "")
    operation_id = str(payload.get("operation_id") or "")
    try:
        if event_type == "create_session":
            await _handle_create_session(payload)
        elif event_type == "customer_message":
            await _handle_customer_message(websocket, payload)
        elif event_type == "human_message":
            await _handle_human_message(payload)
        elif event_type == "set_handover":
            await _handle_handover(payload)
        elif event_type == "mark_read":
            await _handle_mark_read(viewer, payload)
        elif event_type == "ping":
            await realtime_manager.send_json(websocket, {"type": "pong"})
            return
        else:
            raise ValueError(f"Unsupported websocket event type: {event_type}")
    except Exception as exc:
        await realtime_manager.send_json(
            websocket,
            {
                "type": "operation_result",
                "operation_id": operation_id,
                "ok": False,
                "error": str(exc),
            },
        )
        return

    if operation_id:
        await realtime_manager.send_json(
            websocket,
            {
                "type": "operation_result",
                "operation_id": operation_id,
                "ok": True,
                "session_id": payload.get("session_id") or "",
            },
        )


async def _handle_create_session(payload: dict[str, Any]) -> None:
    settings = get_settings()
    with _chat_service() as service:
        state = service.create_welcome_session(
            settings.new_customer_welcome_message_lines,
        )
        payload["session_id"] = state.session_id
        await _broadcast_session_snapshots(service, state.session_id)


async def _handle_customer_message(
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required.")

    session_id = payload.get("session_id") or None
    client_message_id = payload.get("client_message_id") or str(uuid4())

    with _chat_service() as service:
        state = service.persist_customer_message(
            session_id,
            message,
            client_message_id=client_message_id,
        )
        payload["session_id"] = state.session_id
        await _broadcast_session_snapshots(service, state.session_id)

        if state.transfer_flag:
            return

    await _enqueue_customer_auto_reply(
        state.session_id,
        PendingCustomerMessage(
            content=message,
            client_message_id=client_message_id,
        ),
    )


async def _enqueue_customer_auto_reply(
    session_id: str,
    message: PendingCustomerMessage,
) -> None:
    tracker = _AUTO_REPLY_STATES.setdefault(session_id, SessionAutoReplyState())
    tracker.pending.append(message)

    if tracker.task is not None and not tracker.task.done() and not tracker.first_reply_sent:
        tracker.generation += 1
        tracker.task.cancel()

    if tracker.task is None or tracker.task.done() or not tracker.first_reply_sent:
        tracker.generation += 1
        tracker.first_reply_sent = False
        tracker.task = asyncio.create_task(
            _run_auto_reply_worker(session_id, tracker.generation)
        )


async def _run_auto_reply_worker(session_id: str, generation: int) -> None:
    current_task = asyncio.current_task()
    settings = get_settings()
    max_messages = max(1, settings.chat_merge_max_messages)

    try:
        while True:
            tracker = _AUTO_REPLY_STATES.setdefault(
                session_id,
                SessionAutoReplyState(),
            )
            if generation != tracker.generation:
                return
            if not tracker.pending:
                return

            await asyncio.sleep(max(0.0, settings.chat_turn_debounce_seconds))
            batch = tracker.pending[:max_messages]
            del tracker.pending[:max_messages]
            tracker.first_reply_sent = False

            message_text = _format_message_batch(batch)
            first_client_message_id = batch[0].client_message_id if batch else None
            client_message_ids = [
                message.client_message_id
                for message in batch
                if message.client_message_id
            ]
            full_reply = ""
            latest_graph: dict[str, Any] = {}
            turn_id = ""

            try:
                with _chat_service(include_memory_update=False) as service:
                    turn_id = service.create_turn(
                        session_id,
                        trigger_type="customer_auto",
                        input_text=message_text,
                        client_message_ids=client_message_ids,
                    )
                    async for event in service.stream_message(
                        message_text,
                        session_id=session_id,
                        client_message_id=first_client_message_id,
                        turn_id=turn_id,
                        persist_user_message=False,
                        persist_reply_message=False,
                        fallback_on_cancel=False,
                    ):
                        if event.get("session_id"):
                            event = {**event, "session_id": session_id}

                        if event.get("type") == "node_complete":
                            latest_graph = event.get("graph") or latest_graph

                        if (
                            event.get("type") == "node_complete"
                            and event.get("node") == "send"
                            and not tracker.first_reply_sent
                        ):
                            full_reply = str(
                                (event.get("graph") or {}).get("reply") or ""
                            ).strip()
                            if full_reply:
                                tracker.first_reply_sent = True

                        await _broadcast_realtime_event(event)

                        if full_reply and tracker.first_reply_sent:
                            await _send_reply_chunks(
                                service,
                                session_id,
                                full_reply,
                                turn_id=turn_id,
                                delay_seconds=settings.ai_reply_chunk_delay_seconds,
                                max_chars=settings.ai_reply_chunk_max_chars,
                            )
                            full_reply = ""

                        if event.get("type") in {"session", "final"}:
                            await _broadcast_session_snapshots(service, session_id)

                    await _broadcast_session_snapshots(service, session_id)
            except asyncio.CancelledError:
                if turn_id:
                    with _chat_service(include_memory_update=False) as service:
                        if service.repository is not None:
                            service.repository.update_turn(
                                turn_id,
                                status="cancelled",
                                error_message="已被新客户消息合并重跑",
                                completed=True,
                            )
                            service.repository.commit()
                await _broadcast_realtime_event(
                    {
                        "type": "final",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "reply": "",
                        "status": "已被新客户消息合并重跑",
                        "interrupted": True,
                        "cancelled_for_restart": True,
                    }
                )
                raise
            except Exception as exc:
                logger.exception(
                    "Auto reply worker failed for session %s: %s",
                    session_id,
                    exc,
                )
                await _broadcast_realtime_event(
                    {
                        "type": "final",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "reply": "",
                        "status": "自动回复处理异常，已停止本轮自动回复",
                        "interrupted": True,
                    }
                )
                return

            if tracker.first_reply_sent:
                _schedule_memory_update(
                    session_id,
                    customer_message=message_text,
                    reply=str(latest_graph.get("reply") or ""),
                    graph=latest_graph,
                    turn_id=turn_id,
                )

    finally:
        tracker = _AUTO_REPLY_STATES.get(session_id)
        if tracker is not None and tracker.task is current_task:
            tracker.task = None
            tracker.first_reply_sent = False
            if tracker.pending:
                tracker.generation += 1
                tracker.task = asyncio.create_task(
                    _run_auto_reply_worker(session_id, tracker.generation)
                )


async def _broadcast_realtime_event(event: dict[str, Any]) -> None:
    await realtime_manager.broadcast("customer", event)
    await realtime_manager.broadcast("sales", event)


async def _send_reply_chunks(
    service: SalesGraphService,
    session_id: str,
    reply: str,
    *,
    turn_id: str | None = None,
    delay_seconds: float,
    max_chars: int,
) -> None:
    chunks = split_reply_chunks(reply, max_chars=max_chars)
    if not chunks:
        return
    state = service.session_store.get_or_create(session_id)
    saved_any_reply = False
    for index, chunk in enumerate(chunks):
        if index > 0:
            await asyncio.sleep(max(0.0, delay_seconds))
        if service.repository is not None:
            saved_message_id = service.repository.save_message(
                session_id,
                "assistant",
                chunk,
                sender_type="salesagent",
                customer_id=state.customer_id,
                turn_id=turn_id,
            )
            saved_any_reply = saved_any_reply or bool(saved_message_id)
            service.repository.commit()
        await _broadcast_session_snapshots(service, session_id)
    if saved_any_reply and service.repository is not None:
        latest_state = service.repository.get_state(session_id, refresh=True) or state
        service.repository.schedule_followup_after_sales_message(
            latest_state,
            turn_id=turn_id,
        )
        service.repository.commit()
        await _broadcast_session_snapshots(service, session_id)


def _schedule_memory_update(
    session_id: str,
    *,
    customer_message: str,
    reply: str,
    graph: dict[str, Any],
    turn_id: str | None = None,
) -> None:
    if not reply.strip():
        return
    asyncio.create_task(
        _run_memory_update(
            session_id,
            customer_message=customer_message,
            reply=reply,
            graph=graph,
            turn_id=turn_id,
        )
    )


async def _run_memory_update(
    session_id: str,
    *,
    customer_message: str,
    reply: str,
    graph: dict[str, Any],
    turn_id: str | None = None,
) -> None:
    lock = _MEMORY_LOCKS.setdefault(session_id, asyncio.Lock())
    async with lock:
        try:
            with _chat_service(include_memory_update=False) as service:
                result = await service.update_memory_for_exchange(
                    session_id,
                    customer_message=customer_message,
                    reply=reply,
                    graph=graph,
                    turn_id=turn_id,
                )
                if result is not None:
                    await realtime_manager.broadcast_all(
                        {
                            "type": "node_complete",
                            "session_id": session_id,
                            "node": "memory_update",
                            "node_label": "记忆更新",
                            "status": "已完成：记忆更新",
                            "next_node": None,
                            "next_status": "",
                            "state": result.state.model_dump(mode="json"),
                            "graph": {},
                            "runs": result.agent_runs,
                            "completed_runs": len(result.agent_runs),
                        }
                    )
                await _broadcast_session_snapshots(service, session_id)
        except Exception:
            # 记忆更新是后置增强，失败不能影响客户可见对话链路。
            logger.exception("Async memory update failed for session %s", session_id)
            return


def _format_message_batch(messages: list[PendingCustomerMessage]) -> str:
    if len(messages) <= 1:
        return messages[0].content if messages else ""
    lines = [
        f"{index}. {message.content}"
        for index, message in enumerate(messages, start=1)
    ]
    return "客户连续发送了多条消息，请作为同一轮需求一起理解并回复：\n" + "\n".join(lines)


def split_reply_chunks(reply: str, *, max_chars: int) -> list[str]:
    text = re.sub(r"\s+", " ", reply).strip()
    if not text:
        return []
    max_chars = max(12, max_chars)
    parts = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])\s*", text)
        if part.strip()
    ]
    if not parts:
        parts = [text]

    chunks: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            chunks.append(part)
            continue
        buffer = ""
        for segment in re.split(r"(?<=[，,、])", part):
            segment = segment.strip()
            if not segment:
                continue
            if buffer and len(buffer) + len(segment) > max_chars:
                chunks.append(buffer)
                buffer = segment
            elif len(segment) > max_chars:
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.extend(
                    segment[index:index + max_chars]
                    for index in range(0, len(segment), max_chars)
                )
            else:
                buffer = f"{buffer}{segment}" if buffer else segment
        if buffer:
            chunks.append(buffer)
    return chunks


async def _handle_human_message(payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    message = str(payload.get("message") or "").strip()
    if not session_id:
        raise ValueError("session_id is required.")
    if not message:
        raise ValueError("message is required.")

    with _chat_service() as service:
        state = service.persist_human_message(
            session_id,
            message,
            client_message_id=payload.get("client_message_id") or str(uuid4()),
        )
        await _broadcast_session_snapshots(service, state.session_id)


async def _handle_handover(payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        raise ValueError("session_id is required.")

    with _chat_service() as service:
        result = await service.set_handover(
            session_id,
            enabled=bool(payload.get("enabled")),
            reason=str(payload.get("reason") or ""),
        )
        await realtime_manager.broadcast_all(
            {
                "type": "handover_changed",
                "session_id": result.state.session_id,
                "state": result.state.model_dump(mode="json"),
                "agent_runs": result.agent_runs,
            }
        )
        await _broadcast_session_snapshots(service, result.state.session_id)


async def _handle_mark_read(viewer: str, payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        raise ValueError("session_id is required.")

    include_internal = viewer == "sales"
    with _chat_service() as service:
        session = service.mark_session_read(
            session_id,
            viewer_type=viewer,
            include_internal=include_internal,
        )
        if session is not None:
            await realtime_manager.broadcast(
                viewer,
                {
                    "type": "session_updated",
                    "viewer": viewer,
                    "session": session,
                },
            )


async def _broadcast_session_snapshots(
    service: SalesGraphService,
    session_id: str,
) -> None:
    sales_session = service.get_session_snapshot(
        session_id,
        include_internal=True,
        viewer_type="sales",
    )
    if sales_session is not None:
        await realtime_manager.broadcast(
            "sales",
            {
                "type": "session_updated",
                "viewer": "sales",
                "session": sales_session,
            },
        )

    customer_session = service.get_session_snapshot(
        session_id,
        include_internal=False,
        viewer_type="customer",
    )
    if customer_session is not None:
        await realtime_manager.broadcast(
            "customer",
            {
                "type": "session_updated",
                "viewer": "customer",
                "session": customer_session,
            },
        )
