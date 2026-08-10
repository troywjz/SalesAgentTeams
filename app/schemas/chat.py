from typing import Any
from datetime import datetime

from pydantic import BaseModel, Field

from app.conversation import ConversationState


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    client_message_id: str | None = None


class SalesMessageRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)
    client_message_id: str | None = None


class SalesLoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class SalesLoginResponse(BaseModel):
    sales_id: str
    name: str
    email: str
    team: str = ""
    role: str = "sales"
    access_token: str
    token_type: str = "bearer"
    expires_at: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    state: ConversationState
    agent_runs: list[dict[str, Any]]


class MessageSnapshot(BaseModel):
    id: str
    role: str
    text: str
    sender_type: str
    turn_id: str = ""
    customer_id: str = ""
    sales_id: str = ""
    sales_name: str = ""
    client_message_id: str = ""
    created_at: datetime | None = None


class SessionSnapshot(BaseModel):
    session_id: str
    customer_id: str = ""
    sales_id: str = ""
    sales_name: str = ""
    preview: str = ""
    persisted: bool = True
    messages: list[MessageSnapshot] = Field(default_factory=list)
    state: ConversationState | None = None
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    stage_options: list[str] = Field(default_factory=list)
    graph_status: dict[str, Any] | None = None
    sop_followup: dict[str, Any] | None = None
    detail_loaded: bool = False
    isProcessing: bool = False
    processingStatus: str = ""
    latest_message_id: str = ""
    latest_sender_type: str = ""
    latest_message_at: datetime | None = None
    message_count: int = 0
    has_unread: bool = False
    unread_count: int = 0
    read_cursor_message_id: str = ""
    read_cursor_at: datetime | None = None
    reply_mode: str = "ai"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ListSessionsResponse(BaseModel):
    sessions: list[SessionSnapshot] = Field(default_factory=list)


class SessionDetailResponse(BaseModel):
    session: SessionSnapshot


class CreateSessionResponse(BaseModel):
    session: SessionSnapshot


class ResetSessionRequest(BaseModel):
    session_id: str


class ResetSessionResponse(BaseModel):
    session_id: str
    state: ConversationState


class HandoverRequest(BaseModel):
    session_id: str
    enabled: bool
    reason: str = ""


class HandoverResponse(BaseModel):
    session_id: str
    state: ConversationState
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)


class PersistedMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant|system|error)$")
    content: str = Field(min_length=1)
    sender_type: str = Field(
        default="customer",
        pattern="^(customer|salesagent|human|system)$",
    )
    client_message_id: str | None = None


class PersistMessagesRequest(BaseModel):
    session_id: str | None = None
    messages: list[PersistedMessage] = Field(min_length=1)


class PersistMessagesResponse(BaseModel):
    session_id: str
    state: ConversationState


class MarkReadResponse(BaseModel):
    session: SessionSnapshot


class ScheduledMessageTaskPayload(BaseModel):
    name: str = Field(default="定时发送", max_length=128)
    scheduled_at: datetime
    target_mode: str = Field(default="all", pattern="^(all|manual|stage)$")
    target_stage: str = Field(default="", max_length=128)
    selected_session_ids: list[str] = Field(default_factory=list)
    message_text: str = Field(min_length=1)
    enabled: bool = True


class ScheduledMessageTaskSnapshot(BaseModel):
    task_id: str
    name: str
    status: str
    enabled: bool
    scheduled_at: datetime
    target_mode: str
    target_stage: str = ""
    selected_session_ids: list[str] = Field(default_factory=list)
    message_text: str
    sent_session_ids: list[str] = Field(default_factory=list)
    error_message: str = ""
    created_by_sales_id: str = ""
    created_by_sales_name: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    cancelled_at: datetime | None = None


class ScheduledMessageTaskResponse(BaseModel):
    task: ScheduledMessageTaskSnapshot


class ListScheduledMessageTasksResponse(BaseModel):
    tasks: list[ScheduledMessageTaskSnapshot] = Field(default_factory=list)


class ScheduledMessageTargetSnapshot(BaseModel):
    session_id: str
    customer_id: str = ""
    display_name: str = ""
    current_stage: str = ""
    preview: str = ""


class ScheduledMessageTargetsResponse(BaseModel):
    stages: list[str] = Field(default_factory=list)
    customers: list[ScheduledMessageTargetSnapshot] = Field(default_factory=list)
