import json
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents import AgentRunResult
from app.conversation import ConversationState
from app.db.models import (
    ConversationFollowupJob,
    ConversationMemory,
    ConversationReadCursor,
    ConversationSession,
    ConversationSOPState,
    ConversationTurn,
    CustomerRecord,
    KnowledgeSOP,
    LLMCall,
    Message,
    NodeInvocation,
    SalesUser,
    SalesCaseRAGEvent,
    ScheduledMessageTask,
    utc_now,
)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _default_sender_type(role: str) -> str:
    if role == "user":
        return "customer"
    if role == "assistant":
        return "salesagent"
    return "system"


DEFAULT_SALES_ID = "sales-wangjie"
DEFAULT_SALES_NAME = "王杰"
DEFAULT_SALES_TEAM = "A组"
DEFAULT_SALES_EMAIL = "wangjie@salesagent.com"
DEFAULT_SALES_PASSWORD = "123456"
DEFAULT_SALES_ROLE = "sales"


@dataclass(frozen=True)
class SalesIdentity:
    sales_id: str
    name: str


class ChatRepository:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ensure_default_sales_user()

    def ensure_default_sales_user(self) -> SalesUser:
        sales_user = self.db.get(SalesUser, DEFAULT_SALES_ID)
        password_hash = _password_hash(DEFAULT_SALES_PASSWORD)
        if sales_user is None:
            sales_user = SalesUser(
                sales_id=DEFAULT_SALES_ID,
                team=DEFAULT_SALES_TEAM,
                name=DEFAULT_SALES_NAME,
                email=DEFAULT_SALES_EMAIL,
                password_hash=password_hash,
                role=DEFAULT_SALES_ROLE,
            )
            self.db.add(sales_user)
            self.db.flush()
            return sales_user
        sales_user.team = DEFAULT_SALES_TEAM
        sales_user.name = DEFAULT_SALES_NAME
        sales_user.email = DEFAULT_SALES_EMAIL
        sales_user.password_hash = password_hash
        sales_user.role = DEFAULT_SALES_ROLE
        return sales_user

    def default_sales_identity(self) -> SalesIdentity:
        sales_user = self.ensure_default_sales_user()
        return SalesIdentity(sales_id=sales_user.sales_id, name=sales_user.name)

    def get_sales_user_by_email(self, email: str) -> SalesUser | None:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return None
        return self.db.scalar(
            select(SalesUser).where(SalesUser.email == normalized_email)
        )

    def verify_sales_login(self, email: str, password: str) -> SalesUser | None:
        """用销售邮箱和明文密码校验登录，密码只与表内哈希比对。"""
        sales_user = self.get_sales_user_by_email(email)
        if sales_user is None:
            return None
        if sales_user.password_hash != _password_hash(password):
            return None
        return sales_user

    # ── 会话状态 ──

    def get_state(self, session_id: str, *, refresh: bool = False) -> ConversationState | None:
        if refresh:
            self.db.expire_all()
        session = self.db.get(ConversationSession, session_id)
        if session is None:
            return None
        profile = self.db.get(CustomerRecord, session.customer_id)
        memory = self.db.get(ConversationMemory, session.session_id)
        return ConversationState(
            session_id=session.session_id,
            customer_id=session.customer_id,
            current_stage=session.current_stage,
            customer_profile=_profile_from_record(profile),
            history_summary=(
                memory.memory_summary if memory is not None else session.history_summary
            ),
            message_count=session.message_count,
            transfer_flag=session.transfer_flag,
            transfer_reason=session.transfer_reason,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def save_state(self, state: ConversationState) -> None:
        self.save_session_state(state)
        self.save_customer_profile(state)
        self.save_memory(state)

    def save_session_state(self, state: ConversationState) -> None:
        """保存会话主表字段，不写画像和压缩记忆。"""
        if not state.customer_id:
            state.customer_id = str(uuid4())
        sales = self.default_sales_identity()
        # Upsert conversation_sessions
        session = self.db.get(ConversationSession, state.session_id)
        if session is None:
            session = ConversationSession(
                session_id=state.session_id,
                customer_id=state.customer_id,
                sales_id=sales.sales_id,
                sales_name=sales.name,
                current_stage=state.current_stage,
                message_count=state.message_count,
                transfer_flag=state.transfer_flag,
                transfer_reason=state.transfer_reason,
                history_summary="",
            )
            self.db.add(session)
        else:
            session.customer_id = state.customer_id
            session.sales_id = sales.sales_id
            session.sales_name = sales.name
            session.current_stage = state.current_stage
            session.message_count = state.message_count
            session.transfer_flag = state.transfer_flag
            session.transfer_reason = state.transfer_reason

    def save_customer_profile(self, state: ConversationState) -> None:
        # Upsert list_customer.
        if state.customer_id:
            profile = self.db.get(CustomerRecord, state.customer_id)
            cp = state.customer_profile
            if profile is None:
                profile = CustomerRecord(
                    customer_id=state.customer_id,
                    session_id=state.session_id,
                    name=cp.name,
                    age=cp.age,
                    education=cp.education,
                    work_status=cp.work_status,
                    learning_goal=cp.learning_goal,
                    budget=cp.budget,
                    urgency=cp.urgency,
                    concerns_json=_json_dumps(cp.concerns),
                    purchase_intent=cp.purchase_intent,
                )
                self.db.add(profile)
            else:
                profile.session_id = state.session_id
                profile.name = cp.name
                profile.age = cp.age
                profile.education = cp.education
                profile.work_status = cp.work_status
                profile.learning_goal = cp.learning_goal
                profile.budget = cp.budget
                profile.urgency = cp.urgency
                profile.concerns_json = _json_dumps(cp.concerns)
                profile.purchase_intent = cp.purchase_intent

    def save_memory(self, state: ConversationState, *, turn_id: str | None = None) -> None:
        """保存会话压缩记忆，供后续 Agent 作为长期上下文读取。"""
        if not state.session_id:
            return
        if not state.customer_id:
            state.customer_id = str(uuid4())
        sales = self.default_sales_identity()
        memory = self.db.get(ConversationMemory, state.session_id)
        if memory is None:
            memory = ConversationMemory(
                session_id=state.session_id,
                customer_id=state.customer_id,
                sales_id=sales.sales_id,
                sales_name=sales.name,
                memory_summary=state.history_summary,
                last_turn_id=turn_id or "",
            )
            self.db.add(memory)
            return
        memory.customer_id = state.customer_id
        memory.sales_id = sales.sales_id
        memory.sales_name = sales.name
        memory.memory_summary = state.history_summary
        if turn_id is not None:
            memory.last_turn_id = turn_id

    def get_memory(self, session_id: str) -> ConversationMemory | None:
        return self.db.get(ConversationMemory, session_id)

    def list_sessions(self, *, limit: int = 50) -> list[ConversationSession]:
        statement = (
            select(ConversationSession)
            .order_by(ConversationSession.updated_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars())

    def get_session_record(self, session_id: str) -> ConversationSession | None:
        return self.db.get(ConversationSession, session_id)

    # ── 对话回合 ──

    def create_turn(
        self,
        session_id: str,
        *,
        trigger_type: str,
        input_text: str = "",
        client_message_ids: list[str] | None = None,
        parent_turn_id: str = "",
        status: str = "running",
    ) -> ConversationTurn:
        session = self.db.get(ConversationSession, session_id)
        sales = self.default_sales_identity()
        next_index = int(
            self.db.scalar(
                select(func.coalesce(func.max(ConversationTurn.turn_index), 0))
                .where(ConversationTurn.session_id == session_id)
            )
            or 0
        ) + 1
        turn = ConversationTurn(
            turn_id=str(uuid4()),
            session_id=session_id,
            customer_id=getattr(session, "customer_id", "") or "",
            sales_id=getattr(session, "sales_id", "") or sales.sales_id,
            sales_name=getattr(session, "sales_name", "") or sales.name,
            turn_index=next_index,
            trigger_type=trigger_type,
            status=status,
            client_message_ids_json=_json_dumps(client_message_ids or []),
            input_text=input_text,
            parent_turn_id=parent_turn_id,
        )
        self.db.add(turn)
        self.db.flush()
        if session is not None:
            session.latest_turn_id = turn.turn_id
        if client_message_ids:
            self.assign_messages_to_turn(
                session_id,
                turn.turn_id,
                client_message_ids=client_message_ids,
            )
        return turn

    def get_turn(self, turn_id: str) -> ConversationTurn | None:
        return self.db.get(ConversationTurn, turn_id)

    def update_turn(
        self,
        turn_id: str,
        *,
        status: str | None = None,
        reply_text: str | None = None,
        error_message: str | None = None,
        superseded_by_turn_id: str | None = None,
        completed: bool = False,
    ) -> None:
        turn = self.db.get(ConversationTurn, turn_id)
        if turn is None:
            return
        if status is not None:
            turn.status = status
        if reply_text is not None:
            turn.reply_text = reply_text
        if error_message is not None:
            turn.error_message = error_message
        if superseded_by_turn_id is not None:
            turn.superseded_by_turn_id = superseded_by_turn_id
        if completed:
            turn.completed_at = utc_now()

    def assign_messages_to_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        client_message_ids: list[str] | None = None,
        message_ids: list[str] | None = None,
    ) -> list[str]:
        statement = select(Message).where(Message.session_id == session_id)
        if client_message_ids:
            statement = statement.where(Message.client_message_id.in_(client_message_ids))
        elif message_ids:
            statement = statement.where(Message.message_id.in_(message_ids))
        else:
            return []
        messages = list(self.db.execute(statement).scalars())
        message_ids_result: list[str] = []
        for message in messages:
            message.turn_id = turn_id
            message_ids_result.append(message.message_id)
        turn = self.db.get(ConversationTurn, turn_id)
        if turn is not None:
            turn.input_message_ids_json = _json_dumps(message_ids_result)
        return message_ids_result

    # ── 消息 ──

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        sender_type: str | None = None,
        client_message_id: str | None = None,
        customer_id: str | None = None,
        sales_id: str | None = None,
        sales_name: str | None = None,
        turn_id: str | None = None,
    ) -> str:
        if client_message_id and self._message_exists(session_id, client_message_id):
            return ""
        session = self.db.get(ConversationSession, session_id)
        sales = self.default_sales_identity()
        message_id = str(uuid4())
        self.db.add(
            Message(
                message_id=message_id,
                client_message_id=client_message_id or "",
                session_id=session_id,
                turn_id=turn_id or "",
                customer_id=customer_id or getattr(session, "customer_id", "") or "",
                sales_id=sales_id or getattr(session, "sales_id", "") or sales.sales_id,
                sales_name=sales_name or getattr(session, "sales_name", "") or sales.name,
                role=role,
                sender_type=sender_type or _default_sender_type(role),
                content=content,
            )
        )
        return message_id

    def _message_exists(self, session_id: str, client_message_id: str) -> bool:
        statement = select(Message.message_id).where(
            Message.session_id == session_id,
            Message.client_message_id == client_message_id,
        )
        return self.db.execute(statement).first() is not None

    def list_messages(
        self,
        session_id: str,
        *,
        sender_type: str | None = None,
    ) -> list[Message]:
        statement = select(Message).where(Message.session_id == session_id)
        if sender_type is not None:
            statement = statement.where(Message.sender_type == sender_type)
        statement = statement.order_by(Message.created_at, Message.message_id)
        return list(self.db.execute(statement).scalars())

    # ── 节点调用记录 ──

    # -- SOP follow-up runtime --

    def list_sop_rows(self) -> list[KnowledgeSOP]:
        statement = select(KnowledgeSOP).order_by(KnowledgeSOP.sop_id)
        return list(self.db.execute(statement).scalars())

    def get_sop_row(self, stage: str) -> KnowledgeSOP | None:
        if not stage:
            return None
        statement = select(KnowledgeSOP).where(KnowledgeSOP.stage == stage).limit(1)
        return self.db.execute(statement).scalars().first()


    def _sop_timeout_action_for_stage(self, stage: str) -> str:
        row = self.get_sop_row(stage)
        if row is None:
            return "next"
        action = str(row.timeout_action or "").strip().lower()
        return action or "next"

    def _sop_status_for_action(self, action: str) -> str:
        action = str(action or "").strip().lower()
        if action == "pause":
            return "paused"
        if action == "stop":
            return "finished"
        return "active"

    def next_sop_stage(self, current_stage: str) -> str:
        stages = [row.stage for row in self.list_sop_rows() if row.stage]
        deduped: list[str] = []
        for stage in stages:
            if stage not in deduped:
                deduped.append(stage)
        if not deduped:
            return current_stage
        if current_stage not in deduped:
            return deduped[0]
        index = deduped.index(current_stage)
        if index >= len(deduped) - 1:
            return current_stage
        return deduped[index + 1]

    def get_sop_state(self, session_id: str) -> ConversationSOPState | None:
        return self.db.get(ConversationSOPState, session_id)

    def ensure_sop_state(self, state: ConversationState) -> ConversationSOPState:
        sales = self.default_sales_identity()
        sop_state = self.db.get(ConversationSOPState, state.session_id)
        if sop_state is None:
            sop_state = ConversationSOPState(
                session_id=state.session_id,
                customer_id=state.customer_id,
                sales_id=sales.sales_id,
                sales_name=sales.name,
                current_stage=state.current_stage,
                status="handover" if state.transfer_flag else "active",
            )
            self.db.add(sop_state)
            self.db.flush()
            return sop_state
        previous_stage = sop_state.current_stage
        previous_status = sop_state.status
        sop_state.customer_id = state.customer_id
        sop_state.sales_id = sales.sales_id
        sop_state.sales_name = sales.name
        sop_state.current_stage = state.current_stage
        if state.transfer_flag:
            sop_state.status = "handover"
        elif previous_stage == state.current_stage and previous_status in {"paused", "finished"}:
            sop_state.status = previous_status
        else:
            sop_state.status = "active"
        return sop_state

    def cancel_pending_followups(
        self,
        session_id: str,
        reason: str,
        *,
        statuses: tuple[str, ...] = ("pending", "running"),
    ) -> int:
        now = utc_now()
        statement = select(ConversationFollowupJob).where(
            ConversationFollowupJob.session_id == session_id,
            ConversationFollowupJob.status.in_(statuses),
        )
        jobs = list(self.db.execute(statement).scalars())
        for job in jobs:
            job.status = "cancelled"
            job.cancelled_reason = reason
            job.cancelled_at = now
        sop_state = self.db.get(ConversationSOPState, session_id)
        if sop_state is not None:
            sop_state.next_followup_at = None
            if reason == "handover":
                sop_state.status = "handover"
        return len(jobs)

    def note_customer_message_for_sop(self, state: ConversationState) -> None:
        sop_state = self.ensure_sop_state(state)
        sop_state.last_customer_message_at = utc_now()
        sop_state.next_followup_at = None
        if state.transfer_flag:
            sop_state.status = "handover"
        elif sop_state.status not in {"paused", "finished"}:
            sop_state.status = "active"
        self.cancel_pending_followups(state.session_id, "customer_replied")

    def schedule_followup_after_sales_message(
        self,
        state: ConversationState,
        *,
        turn_id: str | None = None,
    ) -> ConversationFollowupJob | None:
        sop_state = self.ensure_sop_state(state)
        sop_state.last_sales_message_at = utc_now()
        if state.transfer_flag:
            self.cancel_pending_followups(state.session_id, "handover")
            return None
        if sop_state.status in {"paused", "finished"}:
            sop_state.next_followup_at = None
            return None

        row = self.get_sop_row(state.current_stage)
        if row is None or int(row.wait_minutes or 0) <= 0:
            sop_state.next_followup_at = None
            return None
        reference_script = str(row.reference_script or "").strip()
        if not reference_script:
            sop_state.next_followup_at = None
            return None

        self.cancel_pending_followups(
            state.session_id,
            "rescheduled",
            statuses=("pending",),
        )
        scheduled_at = utc_now() + timedelta(minutes=int(row.wait_minutes or 0))
        sales = self.default_sales_identity()
        job = ConversationFollowupJob(
            job_id=str(uuid4()),
            session_id=state.session_id,
            customer_id=state.customer_id,
            sales_id=sales.sales_id,
            sales_name=sales.name,
            stage=row.stage,
            status="pending",
            trigger_reason="customer_inactive_timeout",
            reference_script=reference_script,
            timeout_action=str(row.timeout_action or "").strip().lower(),
            scheduled_at=scheduled_at,
            created_turn_id=turn_id or "",
        )
        self.db.add(job)
        sop_state.next_followup_at = scheduled_at
        sop_state.latest_job_id = job.job_id
        sop_state.updated_by_turn_id = turn_id or ""
        return job

    def claim_due_followup_jobs(self, *, limit: int = 10) -> list[ConversationFollowupJob]:
        now = utc_now()
        statement = (
            select(ConversationFollowupJob)
            .where(
                ConversationFollowupJob.status == "pending",
                ConversationFollowupJob.scheduled_at <= now,
            )
            .order_by(ConversationFollowupJob.scheduled_at, ConversationFollowupJob.job_id)
            .limit(limit)
        )
        jobs = list(self.db.execute(statement).scalars())
        for job in jobs:
            job.status = "running"
        return jobs

    def mark_followup_sent(
        self,
        job: ConversationFollowupJob,
        *,
        message_id: str,
        next_stage: str | None = None,
    ) -> None:
        now = utc_now()
        action = str(job.timeout_action or "").strip().lower()
        job.status = "sent"
        job.sent_message_id = message_id
        job.sent_at = now
        sop_state = self.db.get(ConversationSOPState, job.session_id)
        if sop_state is not None:
            sop_state.followup_count += 1
            sop_state.last_sales_message_at = now
            sop_state.next_followup_at = None
            if action == "next" and next_stage:
                sop_state.current_stage = next_stage
            sop_state.status = self._sop_status_for_action(action)

    def mark_followup_cancelled(
        self,
        job: ConversationFollowupJob,
        *,
        reason: str,
    ) -> None:
        job.status = "cancelled"
        job.cancelled_reason = reason
        job.cancelled_at = utc_now()
        sop_state = self.db.get(ConversationSOPState, job.session_id)
        if sop_state is not None and sop_state.latest_job_id == job.job_id:
            sop_state.next_followup_at = None

    def mark_followup_failed(
        self,
        job: ConversationFollowupJob,
        *,
        error_message: str,
    ) -> None:
        job.status = "failed"
        job.error_message = error_message
        sop_state = self.db.get(ConversationSOPState, job.session_id)
        if sop_state is not None and sop_state.latest_job_id == job.job_id:
            sop_state.next_followup_at = None

    # -- Manual scheduled outbound messages --

    def list_scheduled_message_tasks(self, *, limit: int = 100) -> list[ScheduledMessageTask]:
        statement = (
            select(ScheduledMessageTask)
            .order_by(ScheduledMessageTask.scheduled_at.desc(), ScheduledMessageTask.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars())

    def get_scheduled_message_task(self, task_id: str) -> ScheduledMessageTask | None:
        return self.db.get(ScheduledMessageTask, task_id)

    def create_scheduled_message_task(
        self,
        *,
        name: str,
        scheduled_at,
        target_mode: str,
        target_stage: str,
        selected_session_ids: list[str],
        message_text: str,
        enabled: bool = True,
    ) -> ScheduledMessageTask:
        sales = self.default_sales_identity()
        task = ScheduledMessageTask(
            task_id=str(uuid4()),
            name=name.strip() or "定时发送",
            status="pending",
            enabled=enabled,
            scheduled_at=scheduled_at,
            target_mode=_normalize_target_mode(target_mode),
            target_stage=str(target_stage or "").strip(),
            selected_session_ids_json=_json_dumps(_dedupe(selected_session_ids)),
            message_text=message_text.strip(),
            created_by_sales_id=sales.sales_id,
            created_by_sales_name=sales.name,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def update_scheduled_message_task(
        self,
        task: ScheduledMessageTask,
        *,
        name: str,
        scheduled_at,
        target_mode: str,
        target_stage: str,
        selected_session_ids: list[str],
        message_text: str,
        enabled: bool = True,
    ) -> ScheduledMessageTask:
        if task.status in {"sent", "running"}:
            return task
        task.name = name.strip() or task.name or "定时发送"
        task.scheduled_at = scheduled_at
        task.target_mode = _normalize_target_mode(target_mode)
        task.target_stage = str(target_stage or "").strip()
        task.selected_session_ids_json = _json_dumps(_dedupe(selected_session_ids))
        task.message_text = message_text.strip()
        task.enabled = enabled
        task.status = "pending" if enabled else "cancelled"
        if not enabled:
            task.cancelled_at = utc_now()
        else:
            task.cancelled_at = None
            task.error_message = ""
        return task

    def cancel_scheduled_message_task(self, task: ScheduledMessageTask) -> None:
        if task.status in {"sent", "running"}:
            return
        task.status = "cancelled"
        task.enabled = False
        task.cancelled_at = utc_now()

    def claim_due_scheduled_message_tasks(self, *, limit: int = 10) -> list[ScheduledMessageTask]:
        now = utc_now()
        statement = (
            select(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.status == "pending",
                ScheduledMessageTask.enabled.is_(True),
                ScheduledMessageTask.scheduled_at <= now,
            )
            .order_by(ScheduledMessageTask.scheduled_at, ScheduledMessageTask.task_id)
            .limit(limit)
        )
        tasks = list(self.db.execute(statement).scalars())
        for task in tasks:
            task.status = "running"
        return tasks

    def resolve_scheduled_message_targets(self, task: ScheduledMessageTask) -> list[ConversationSession]:
        statement = select(ConversationSession)
        session_ids = _json_loads_list(task.selected_session_ids_json)
        if task.target_mode == "manual":
            if not session_ids:
                return []
            statement = statement.where(ConversationSession.session_id.in_(session_ids))
        elif task.target_mode == "stage":
            statement = statement.where(ConversationSession.current_stage == task.target_stage)
            if session_ids:
                statement = statement.where(ConversationSession.session_id.in_(session_ids))
        elif session_ids:
            statement = statement.where(ConversationSession.session_id.in_(session_ids))
        statement = statement.order_by(ConversationSession.updated_at.desc(), ConversationSession.session_id)
        return list(self.db.execute(statement).scalars())

    def list_scheduled_message_target_options(
        self,
        *,
        target_mode: str = "all",
        target_stage: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        mode = _normalize_target_mode(target_mode)
        statement = select(ConversationSession, CustomerRecord).join(
            CustomerRecord,
            CustomerRecord.customer_id == ConversationSession.customer_id,
            isouter=True,
        )
        if mode == "stage":
            statement = statement.where(ConversationSession.current_stage == target_stage)
        statement = statement.order_by(ConversationSession.updated_at.desc(), ConversationSession.session_id).limit(limit)
        rows = self.db.execute(statement).all()
        return [
            {
                "session_id": session.session_id,
                "customer_id": session.customer_id,
                "display_name": customer.name if customer and customer.name else session.session_id,
                "current_stage": session.current_stage,
                "preview": session.history_summary or "",
            }
            for session, customer in rows
        ]

    def list_scheduled_message_stages(self) -> list[str]:
        stages: list[str] = []
        for row in self.db.execute(select(KnowledgeSOP.stage).order_by(KnowledgeSOP.sop_id)).scalars():
            if row and row not in stages:
                stages.append(row)
        for row in self.db.execute(select(ConversationSession.current_stage).order_by(ConversationSession.current_stage)).scalars():
            if row and row not in stages:
                stages.append(row)
        return stages

    def mark_scheduled_message_task_sent(
        self,
        task: ScheduledMessageTask,
        *,
        sent_session_ids: list[str],
    ) -> None:
        task.status = "sent"
        task.enabled = False
        task.sent_session_ids_json = _json_dumps(_dedupe(sent_session_ids))
        task.sent_at = utc_now()
        task.error_message = ""

    def mark_scheduled_message_task_failed(
        self,
        task: ScheduledMessageTask,
        *,
        error_message: str,
    ) -> None:
        task.status = "failed"
        task.enabled = False
        task.error_message = error_message

    def list_node_invocations(self, session_id: str) -> list[NodeInvocation]:
        statement = (
            select(NodeInvocation)
            .where(NodeInvocation.session_id == session_id)
            .order_by(NodeInvocation.created_at, NodeInvocation.invocation_id)
        )
        return list(self.db.execute(statement).scalars())

    def list_llm_calls(self, session_id: str) -> list[LLMCall]:
        statement = (
            select(LLMCall)
            .where(LLMCall.session_id == session_id)
            .order_by(LLMCall.created_at, LLMCall.call_id)
        )
        return list(self.db.execute(statement).scalars())

    def save_node_invocations(
        self,
        session_id: str,
        runs: list[AgentRunResult],
        *,
        turn_id: str | None = None,
    ) -> None:
        for run in runs:
            invocation_id = str(uuid4())
            self.db.add(
                NodeInvocation(
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id or "",
                    node_name=run.agent_name,
                    model_provider=run.provider,
                    model_name=run.model,
                    elapsed_ms=run.elapsed_ms,
                    success=1 if run.success else 0,
                    error_message=run.error_message,
                    input_json=_json_dumps(run.input_payload),
                    output_json=_json_dumps(run.output),
                    raw_output=run.raw_output,
                )
            )
            self._save_llm_calls(
                session_id,
                turn_id=turn_id or "",
                node_invocation_id=invocation_id,
                node_name=run.agent_name,
                calls=run.llm_call_attempts,
            )
            self._save_sales_case_rag_event(
                session_id,
                turn_id=turn_id or "",
                node_invocation_id=invocation_id,
                run=run,
            )

    def _save_llm_calls(
        self,
        session_id: str,
        *,
        turn_id: str,
        node_invocation_id: str,
        node_name: str,
        calls: list[Any],
    ) -> None:
        for call in calls:
            self.db.add(
                LLMCall(
                    call_id=str(uuid4()),
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=node_invocation_id,
                    node_name=node_name,
                    provider=call.provider,
                    model_name=call.model,
                    api_url=call.api_url,
                    protocol=call.protocol,
                    attempt_index=call.attempt_index,
                    elapsed_ms=call.elapsed_ms,
                    success=1 if call.success else 0,
                    error_type=call.error_type,
                    error_message=call.error_message,
                    request_json=_json_dumps(call.request_json),
                    response_json=_json_dumps(call.response_json),
                    usage_json=_json_dumps(call.usage),
                )
            )

    def _save_sales_case_rag_event(
        self,
        session_id: str,
        *,
        turn_id: str,
        node_invocation_id: str,
        run: AgentRunResult,
    ) -> None:
        if run.agent_name == "sales_case_rag":
            references = _sales_case_references(run.output)
            scores = _sales_case_scores(references)
            event = SalesCaseRAGEvent(
                event_id=str(uuid4()),
                session_id=session_id,
                turn_id=turn_id,
                enabled=True,
                hit_count=len(references),
                used=False,
                query_text=str(run.input_payload.get("message") or ""),
                reference_ids_json=_json_dumps(_sales_case_reference_ids(references)),
                scores_json=_json_dumps(scores),
                max_score=max(scores) if scores else 0.0,
                avg_score=(sum(scores) / len(scores)) if scores else 0.0,
                used_reference_ids_json="[]",
                used_strategy="",
                elapsed_ms=run.elapsed_ms,
            )
            self.db.add(event)
            self.db.flush()
            return

        if run.agent_name != "conversation":
            return
        references = _sales_case_references(run.input_payload)
        if not references:
            return
        event = self.db.scalar(
            select(SalesCaseRAGEvent)
            .where(SalesCaseRAGEvent.session_id == session_id)
            .where(SalesCaseRAGEvent.turn_id == turn_id)
            .order_by(SalesCaseRAGEvent.created_at.desc())
        )
        if event is None:
            return
        event.used = True
        event.used_reference_ids_json = _json_dumps(_sales_case_reference_ids(references))
        event.used_strategy = "注入回复生成"

    # ── 兼容旧接口（内部转发到新方法） ──

    def list_agent_runs(self, session_id: str) -> list[NodeInvocation]:
        return self.list_node_invocations(session_id)

    def save_agent_runs(self, session_id: str, runs: list[AgentRunResult]) -> None:
        self.save_node_invocations(session_id, runs)

    # ── 已读游标 ──

    def get_read_cursor(
        self,
        session_id: str,
        viewer_type: str,
    ) -> ConversationReadCursor | None:
        return self.db.get(
            ConversationReadCursor,
            _read_cursor_id(session_id, viewer_type),
        )

    def save_read_cursor(
        self,
        session_id: str,
        viewer_type: str,
        message: Message,
    ) -> ConversationReadCursor:
        cursor_id = _read_cursor_id(session_id, viewer_type)
        cursor = self.db.get(ConversationReadCursor, cursor_id)
        if cursor is None:
            cursor = ConversationReadCursor(
                cursor_id=cursor_id,
                session_id=session_id,
                viewer_type=viewer_type,
            )
            self.db.add(cursor)
        cursor.last_read_message_id = message.client_message_id or message.message_id
        cursor.last_read_at = message.created_at
        return cursor

    # ── 清理 ──

    def clear_session_activity(self, session_id: str) -> None:
        self.db.execute(delete(Message).where(Message.session_id == session_id))
        self.db.execute(delete(ConversationTurn).where(ConversationTurn.session_id == session_id))
        self.db.execute(delete(LLMCall).where(LLMCall.session_id == session_id))
        self.db.execute(delete(NodeInvocation).where(NodeInvocation.session_id == session_id))
        self.db.execute(delete(ConversationMemory).where(ConversationMemory.session_id == session_id))
        self.db.execute(delete(ConversationFollowupJob).where(ConversationFollowupJob.session_id == session_id))
        self.db.execute(delete(ConversationSOPState).where(ConversationSOPState.session_id == session_id))
        tasks = list(self.db.execute(select(ScheduledMessageTask)).scalars())
        for task in tasks:
            selected = _json_loads_list(task.selected_session_ids_json)
            sent = _json_loads_list(task.sent_session_ids_json)
            if session_id in selected or session_id in sent:
                task.selected_session_ids_json = _json_dumps([item for item in selected if item != session_id])
                task.sent_session_ids_json = _json_dumps([item for item in sent if item != session_id])

    def commit(self) -> None:
        self.db.commit()


def _json_loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_target_mode(value: str) -> str:
    value = str(value or "").strip().lower()
    if value in {"manual", "stage"}:
        return value
    return "all"


def _read_cursor_id(session_id: str, viewer_type: str) -> str:
    return f"{session_id}:{viewer_type}"


def _sales_case_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("sales_case_references") or payload.get("references") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _sales_case_reference_ids(references: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for reference in references:
        value = str(reference.get("chunk_id") or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _sales_case_scores(references: list[dict[str, Any]]) -> list[float]:
    scores: list[float] = []
    for reference in references:
        raw_score = reference.get("similarity", reference.get("quality_score", 0.0))
        try:
            scores.append(float(raw_score))
        except (TypeError, ValueError):
            continue
    return scores


def _profile_from_record(profile: CustomerRecord | None) -> dict[str, Any]:
    """从数据库记录构造 CustomerProfile 初始化参数。"""
    if profile is None:
        return {}
    concerns = json.loads(profile.concerns_json) if profile.concerns_json else []
    return {
        "name": profile.name,
        "age": profile.age,
        "education": profile.education,
        "work_status": profile.work_status,
        "learning_goal": profile.learning_goal,
        "budget": profile.budget,
        "urgency": profile.urgency,
        "concerns": concerns,
        "purchase_intent": profile.purchase_intent,
    }


def _password_hash(raw_password: str) -> str:
    return sha256(raw_password.encode("utf-8")).hexdigest()
