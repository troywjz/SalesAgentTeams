import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.auth import issue_auth_token, require_sales_auth
from app.core.config import get_settings
from app.core.time import to_beijing_time
from app.db import SessionLocal
from app.graph import SalesGraphService
from app.llm import LLMConfigurationError, LLMProviderError, create_llm_client
from app.repositories import ChatRepository
from app.schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionResponse,
    HandoverRequest,
    HandoverResponse,
    ListSessionsResponse,
    MarkReadResponse,
    PersistMessagesRequest,
    PersistMessagesResponse,
    ResetSessionRequest,
    ResetSessionResponse,
    SalesLoginRequest,
    SalesLoginResponse,
    SalesMessageRequest,
    ListScheduledMessageTasksResponse,
    ScheduledMessageTargetsResponse,
    ScheduledMessageTaskPayload,
    ScheduledMessageTaskResponse,
    ScheduledMessageTaskSnapshot,
    SessionDetailResponse,
)


router = APIRouter(prefix="/chat", tags=["chat"])


async def get_chat_service() -> AsyncGenerator[SalesGraphService, None]:
    """Create a fresh graph service per request to avoid shared DB session issues."""
    db = SessionLocal()
    repository = ChatRepository(db)
    settings = get_settings()
    chat_service = SalesGraphService(
        create_llm_client(settings),
        repository=repository,
        request_timeout_seconds=settings.chat_request_timeout_seconds,
    )
    try:
        yield chat_service
    finally:
        db.close()


def _create_welcome_session_response(
    chat_service: SalesGraphService,
    *,
    viewer_type: str,
    include_internal: bool,
) -> CreateSessionResponse:
    settings = get_settings()
    state = chat_service.create_welcome_session(
        settings.new_customer_welcome_message_lines,
    )
    session = chat_service.get_session_snapshot(
        state.session_id,
        include_internal=include_internal,
        viewer_type=viewer_type,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session creation failed.",
        )
    return CreateSessionResponse(session=session)


def _loads_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _scheduled_task_snapshot(task) -> ScheduledMessageTaskSnapshot:
    return ScheduledMessageTaskSnapshot(
        task_id=task.task_id,
        name=task.name,
        status=task.status,
        enabled=task.enabled,
        scheduled_at=to_beijing_time(task.scheduled_at),
        target_mode=task.target_mode,
        target_stage=task.target_stage,
        selected_session_ids=_loads_string_list(task.selected_session_ids_json),
        message_text=task.message_text,
        sent_session_ids=_loads_string_list(task.sent_session_ids_json),
        error_message=task.error_message,
        created_by_sales_id=task.created_by_sales_id,
        created_by_sales_name=task.created_by_sales_name,
        created_at=to_beijing_time(task.created_at),
        updated_at=to_beijing_time(task.updated_at),
        sent_at=to_beijing_time(task.sent_at),
        cancelled_at=to_beijing_time(task.cancelled_at),
    )


@router.post("/sales/login", response_model=SalesLoginResponse)
async def login_sales(
    request: SalesLoginRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> SalesLoginResponse:
    sales_user = chat_service.repository.verify_sales_login(
        request.email,
        request.password,
    )
    if sales_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误。",
        )
    token = issue_auth_token(
        subject=sales_user.sales_id,
        scope="sales",
        display_name=sales_user.name,
    )
    return SalesLoginResponse(
        sales_id=sales_user.sales_id,
        name=sales_user.name,
        email=sales_user.email,
        team=sales_user.team,
        role=sales_user.role,
        **token,
    )


@router.get("/sessions", response_model=ListSessionsResponse)
async def list_sessions(
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ListSessionsResponse:
    return ListSessionsResponse(
        sessions=chat_service.list_session_snapshots(viewer_type="sales")
    )


@router.post("/sales/sessions", response_model=CreateSessionResponse)
async def create_sales_session(
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> CreateSessionResponse:
    return _create_welcome_session_response(
        chat_service,
        viewer_type="sales",
        include_internal=True,
    )


@router.post("/customer/sessions", response_model=CreateSessionResponse)
async def create_customer_session(
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> CreateSessionResponse:
    return _create_welcome_session_response(
        chat_service,
        viewer_type="customer",
        include_internal=False,
    )


@router.get("/sales/sessions", response_model=ListSessionsResponse)
async def list_sales_sessions(
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ListSessionsResponse:
    return ListSessionsResponse(
        sessions=chat_service.list_session_snapshots(
            include_internal=True,
            viewer_type="sales",
        )
    )


@router.get("/sales/scheduled-tasks", response_model=ListScheduledMessageTasksResponse)
async def list_scheduled_message_tasks(
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ListScheduledMessageTasksResponse:
    tasks = chat_service.repository.list_scheduled_message_tasks()
    return ListScheduledMessageTasksResponse(
        tasks=[_scheduled_task_snapshot(task) for task in tasks]
    )


@router.post("/sales/scheduled-tasks", response_model=ScheduledMessageTaskResponse)
async def create_scheduled_message_task(
    request: ScheduledMessageTaskPayload,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ScheduledMessageTaskResponse:
    task = chat_service.repository.create_scheduled_message_task(
        name=request.name,
        scheduled_at=request.scheduled_at,
        target_mode=request.target_mode,
        target_stage=request.target_stage,
        selected_session_ids=request.selected_session_ids,
        message_text=request.message_text,
        enabled=request.enabled,
    )
    chat_service.repository.commit()
    return ScheduledMessageTaskResponse(task=_scheduled_task_snapshot(task))


@router.put("/sales/scheduled-tasks/{task_id}", response_model=ScheduledMessageTaskResponse)
async def update_scheduled_message_task(
    task_id: str,
    request: ScheduledMessageTaskPayload,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ScheduledMessageTaskResponse:
    task = chat_service.repository.get_scheduled_message_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled task not found.",
        )
    task = chat_service.repository.update_scheduled_message_task(
        task,
        name=request.name,
        scheduled_at=request.scheduled_at,
        target_mode=request.target_mode,
        target_stage=request.target_stage,
        selected_session_ids=request.selected_session_ids,
        message_text=request.message_text,
        enabled=request.enabled,
    )
    chat_service.repository.commit()
    return ScheduledMessageTaskResponse(task=_scheduled_task_snapshot(task))


@router.delete("/sales/scheduled-tasks/{task_id}", response_model=ScheduledMessageTaskResponse)
async def delete_scheduled_message_task(
    task_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ScheduledMessageTaskResponse:
    task = chat_service.repository.get_scheduled_message_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled task not found.",
        )
    chat_service.repository.cancel_scheduled_message_task(task)
    chat_service.repository.commit()
    return ScheduledMessageTaskResponse(task=_scheduled_task_snapshot(task))


@router.get("/sales/scheduled-task-targets", response_model=ScheduledMessageTargetsResponse)
async def list_scheduled_message_targets(
    target_mode: str = "all",
    target_stage: str = "",
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ScheduledMessageTargetsResponse:
    return ScheduledMessageTargetsResponse(
        stages=chat_service.repository.list_scheduled_message_stages(),
        customers=chat_service.repository.list_scheduled_message_target_options(
            target_mode=target_mode,
            target_stage=target_stage,
        ),
    )


@router.get("/customer/sessions", response_model=ListSessionsResponse)
async def list_customer_sessions(
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> ListSessionsResponse:
    return ListSessionsResponse(
        sessions=chat_service.list_session_snapshots(
            include_internal=False,
            viewer_type="customer",
        )
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> SessionDetailResponse:
    session = chat_service.get_session_snapshot(session_id, viewer_type="sales")
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return SessionDetailResponse(session=session)


@router.get("/sales/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_sales_session_detail(
    session_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> SessionDetailResponse:
    session = chat_service.get_session_snapshot(
        session_id,
        include_internal=True,
        viewer_type="sales",
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return SessionDetailResponse(session=session)


@router.get("/customer/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_customer_session_detail(
    session_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> SessionDetailResponse:
    session = chat_service.get_session_snapshot(
        session_id,
        include_internal=False,
        viewer_type="customer",
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return SessionDetailResponse(session=session)


@router.post("/sales/sessions/{session_id}/read", response_model=MarkReadResponse)
async def mark_sales_session_read(
    session_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> MarkReadResponse:
    session = chat_service.mark_session_read(
        session_id,
        viewer_type="sales",
        include_internal=True,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return MarkReadResponse(session=session)


@router.post("/customer/sessions/{session_id}/read", response_model=MarkReadResponse)
async def mark_customer_session_read(
    session_id: str,
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> MarkReadResponse:
    session = chat_service.mark_session_read(
        session_id,
        viewer_type="customer",
        include_internal=False,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return MarkReadResponse(session=session)


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ChatResponse:
    try:
        result = await chat_service.process_message(
            request.message,
            session_id=request.session_id,
            client_message_id=request.client_message_id,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return ChatResponse(
        session_id=result.state.session_id,
        reply=result.reply,
        state=result.state,
        agent_runs=result.agent_runs,
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> StreamingResponse:
    async def event_lines() -> AsyncGenerator[str, None]:
        async for event in chat_service.stream_message(
            request.message,
            session_id=request.session_id,
            client_message_id=request.client_message_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        event_lines(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/customer/messages/stream")
async def customer_message_stream(
    request: ChatRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
) -> StreamingResponse:
    async def event_lines() -> AsyncGenerator[str, None]:
        async for event in chat_service.stream_message(
            request.message,
            session_id=request.session_id,
            client_message_id=request.client_message_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        event_lines(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/sales/messages", response_model=PersistMessagesResponse)
async def sales_message(
    request: SalesMessageRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> PersistMessagesResponse:
    state = chat_service.persist_human_message(
        request.session_id,
        request.message,
        client_message_id=request.client_message_id,
    )
    return PersistMessagesResponse(session_id=state.session_id, state=state)


@router.post("/sales/handover", response_model=HandoverResponse)
async def set_sales_handover(
    request: HandoverRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> HandoverResponse:
    result = await chat_service.set_handover(
        request.session_id,
        enabled=request.enabled,
        reason=request.reason,
    )
    return HandoverResponse(
        session_id=result.state.session_id,
        state=result.state,
        agent_runs=result.agent_runs,
    )


@router.post("/handover", response_model=HandoverResponse)
async def set_handover(
    request: HandoverRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> HandoverResponse:
    result = await chat_service.set_handover(
        request.session_id,
        enabled=request.enabled,
        reason=request.reason,
    )
    return HandoverResponse(
        session_id=result.state.session_id,
        state=result.state,
        agent_runs=result.agent_runs,
    )


@router.post("/messages", response_model=PersistMessagesResponse)
async def persist_messages(
    request: PersistMessagesRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> PersistMessagesResponse:
    state = chat_service.persist_messages(
        request.session_id,
        [message.model_dump() for message in request.messages],
    )
    return PersistMessagesResponse(session_id=state.session_id, state=state)


@router.post("/reset", response_model=ResetSessionResponse)
async def reset_session(
    request: ResetSessionRequest,
    chat_service: SalesGraphService = Depends(get_chat_service),
    _auth: dict = Depends(require_sales_auth),
) -> ResetSessionResponse:
    state = chat_service.reset_session(request.session_id)
    return ResetSessionResponse(session_id=state.session_id, state=state)
