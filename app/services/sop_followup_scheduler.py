from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents import SafetyAgent
from app.conversation import ConversationState
from app.core.config import get_settings
from app.db import SessionLocal
from app.db.models import ConversationFollowupJob, ScheduledMessageTask
from app.graph import SalesGraphService
from app.graph.nodes import _as_dict
from app.graph.service import _append_history_line
from app.knowledge import KnowledgeLoader
from app.llm import create_llm_client
from app.realtime import realtime_manager
from app.repositories import ChatRepository

logger = logging.getLogger(__name__)
_task: asyncio.Task[None] | None = None
_tick_lock = asyncio.Lock()


def start_sop_followup_scheduler() -> None:
    settings = get_settings()
    if not settings.sop_followup_enabled:
        logger.info("SOP followup scheduler disabled by SOP_FOLLOWUP_ENABLED=false")
        return
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_worker(), name="sop-followup-scheduler")
        logger.info("SOP followup scheduler started")


async def stop_sop_followup_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("SOP followup scheduler stopped")


async def _worker() -> None:
    settings = get_settings()
    interval = max(1.0, settings.sop_followup_poll_interval_seconds)
    while True:
        try:
            await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SOP followup scheduler tick failed")
        await asyncio.sleep(interval)


async def _run_once() -> None:
    settings = get_settings()
    if _tick_lock.locked():
        logger.debug("SOP followup scheduler tick skipped because the local worker is still running")
        return
    async with _tick_lock:
        with SessionLocal() as db:
            repository = ChatRepository(db)
            jobs = repository.claim_due_followup_jobs(
                limit=max(1, settings.sop_followup_batch_size),
            )
            scheduled_tasks = repository.claim_due_scheduled_message_tasks(
                limit=max(1, settings.sop_followup_batch_size),
            )
            repository.commit()
            for job in jobs:
                await _process_job(repository, job)
            for task in scheduled_tasks:
                await _process_scheduled_message_task(repository, task)


async def _process_job(
    repository: ChatRepository,
    job: ConversationFollowupJob,
) -> None:
    settings = get_settings()
    knowledge_loader = KnowledgeLoader()
    service = SalesGraphService(
        create_llm_client(settings),
        repository=repository,
        knowledge_loader=knowledge_loader,
        request_timeout_seconds=settings.chat_request_timeout_seconds,
        include_memory_update=False,
    )
    state = repository.get_state(job.session_id, refresh=True)
    if state is None:
        repository.mark_followup_failed(job, error_message="session_not_found")
        repository.commit()
        return
    if state.transfer_flag:
        repository.mark_followup_cancelled(job, reason="handover")
        repository.commit()
        await _broadcast_session_snapshots(service, job.session_id)
        return

    turn = repository.create_turn(
        job.session_id,
        trigger_type="sop_followup",
        input_text=job.reference_script,
        status="running",
    )
    safety_agent = SafetyAgent(create_llm_client(settings))
    try:
        run = await safety_agent.run(
            {
                "message": "Customer has not replied for a while; the system is preparing an SOP follow-up message.",
                "draft_reply": job.reference_script,
                "intent": {},
                "sop_decision": {
                    "current_stage": job.stage,
                    "trigger_reason": job.trigger_reason,
                    "timeout_action": job.timeout_action,
                },
                "customer_profile": state.customer_profile.model_dump(),
                "current_stage": state.current_stage,
                "safety_rules": knowledge_loader.load_safety_rules(),
                "source": "sop_followup_scheduler",
            }
        )
        safety = _as_dict(run.output)
        action = str(safety.get("action") or "pass").lower()
        if action in {"transfer", "block"}:
            repository.save_node_invocations(job.session_id, [run], turn_id=turn.turn_id)
            repository.mark_followup_failed(job, error_message=f"safety_{action}")
            repository.update_turn(
                turn.turn_id,
                status="blocked",
                error_message=f"SOP follow-up blocked by safety: {action}",
                completed=True,
            )
            repository.commit()
            await _broadcast_session_snapshots(service, job.session_id)
            return

        reply = str(
            safety.get("approved_reply")
            or safety.get("revised_reply")
            or job.reference_script
        ).strip()
        timeout_action = str(job.timeout_action or "").strip().lower()
        next_stage = repository.next_sop_stage(job.stage) if timeout_action == "next" else None
        if not reply:
            repository.save_node_invocations(job.session_id, [run], turn_id=turn.turn_id)
            repository.mark_followup_failed(job, error_message="empty_reply_after_safety")
            repository.update_turn(
                turn.turn_id,
                status="failed",
                error_message="SOP follow-up reply is empty",
                completed=True,
            )
            repository.commit()
            await _broadcast_session_snapshots(service, job.session_id)
            return

        message_id = repository.save_message(
            job.session_id,
            "assistant",
            reply,
            sender_type="salesagent",
            customer_id=state.customer_id,
            turn_id=turn.turn_id,
        )
        _append_history_line(state, "assistant", "salesagent", reply)
        if timeout_action == "next":
            state.current_stage = next_stage or job.stage
        state.touch()
        repository.save_node_invocations(job.session_id, [run], turn_id=turn.turn_id)
        repository.save_session_state(state)
        repository.save_memory(state, turn_id=turn.turn_id)
        repository.mark_followup_sent(
            job,
            message_id=message_id,
            next_stage=state.current_stage,
        )
        if timeout_action == "next":
            repository.schedule_followup_after_sales_message(
                state,
                turn_id=turn.turn_id,
            )
        repository.update_turn(
            turn.turn_id,
            status="sent",
            reply_text=reply,
            completed=True,
        )
        repository.commit()
        await _broadcast_session_snapshots(service, job.session_id)
    except Exception as exc:
        logger.exception("SOP followup job failed: %s", job.job_id)
        repository.mark_followup_failed(job, error_message=str(exc))
        repository.update_turn(
            turn.turn_id,
            status="failed",
            error_message=str(exc),
            completed=True,
        )
        repository.commit()
        await _broadcast_session_snapshots(service, job.session_id)


async def _process_scheduled_message_task(
    repository: ChatRepository,
    task: ScheduledMessageTask,
) -> None:
    settings = get_settings()
    service = SalesGraphService(
        create_llm_client(settings),
        repository=repository,
        knowledge_loader=KnowledgeLoader(),
        request_timeout_seconds=settings.chat_request_timeout_seconds,
        include_memory_update=False,
    )
    text = str(task.message_text or "").strip()
    if not text:
        repository.mark_scheduled_message_task_failed(task, error_message="empty_message")
        repository.commit()
        return

    sent_session_ids: list[str] = []
    try:
        target_sessions = repository.resolve_scheduled_message_targets(task)
        if not target_sessions:
            repository.mark_scheduled_message_task_failed(task, error_message="no_targets")
            repository.commit()
            return

        for target in target_sessions:
            state = repository.get_state(target.session_id, refresh=True)
            if state is None:
                continue
            turn = repository.create_turn(
                target.session_id,
                trigger_type="scheduled_message",
                input_text=text,
                status="running",
            )
            message_id = repository.save_message(
                target.session_id,
                "assistant",
                text,
                sender_type="salesagent",
                customer_id=state.customer_id,
                turn_id=turn.turn_id,
            )
            _append_history_line(state, "assistant", "salesagent", text)
            state.touch()
            repository.save_session_state(state)
            repository.save_memory(state, turn_id=turn.turn_id)
            repository.update_turn(
                turn.turn_id,
                status="sent",
                reply_text=text,
                completed=True,
            )
            repository.schedule_followup_after_sales_message(state, turn_id=turn.turn_id)
            if message_id:
                sent_session_ids.append(target.session_id)

        if not sent_session_ids:
            repository.mark_scheduled_message_task_failed(task, error_message="no_messages_sent")
        else:
            repository.mark_scheduled_message_task_sent(
                task,
                sent_session_ids=sent_session_ids,
            )
        repository.commit()
        for session_id in sent_session_ids:
            await _broadcast_session_snapshots(service, session_id)
    except Exception as exc:
        logger.exception("Scheduled message task failed: %s", task.task_id)
        repository.mark_scheduled_message_task_failed(task, error_message=str(exc))
        repository.commit()
        for session_id in sent_session_ids:
            await _broadcast_session_snapshots(service, session_id)


async def _broadcast_session_snapshots(
    service: SalesGraphService,
    session_id: str,
) -> None:
    for viewer, include_internal in (("sales", True), ("customer", False)):
        session = service.get_session_snapshot(
            session_id,
            include_internal=include_internal,
            viewer_type=viewer,
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
