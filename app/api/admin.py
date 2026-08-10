from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import issue_auth_token, require_admin_auth, verify_admin_password
from app.core.config import get_settings
from app.db import SessionLocal
from app.services.admin_dashboard_service import AdminDashboardService
from app.services.admin_config_service import AdminConfigService


router = APIRouter(prefix="/admin", tags=["admin"])


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AdminConfigUpdateRequest(BaseModel):
    updates: dict[str, object] = Field(default_factory=dict)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/login")
async def login_admin(request: AdminLoginRequest) -> dict[str, Any]:
    settings = get_settings()
    if not verify_admin_password(request.username, request.password, settings=settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理员账号或密码错误。",
        )
    token = issue_auth_token(
        subject=request.username.strip(),
        scope="admin",
        display_name="管理员",
        settings=settings,
    )
    return {
        "username": request.username.strip(),
        "role": "admin",
        **token,
    }


@router.get("/config")
async def get_admin_config(
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, object]:
    return AdminConfigService().list_items()


@router.put("/config")
async def update_admin_config(
    request: AdminConfigUpdateRequest,
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, object]:
    try:
        return AdminConfigService().update_items(request.updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/restart")
async def restart_admin_service(
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, object]:
    return AdminConfigService().restart()


@router.get("/dashboard/summary")
async def dashboard_summary(
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).summary()


@router.get("/dashboard/timeseries")
async def dashboard_timeseries(
    range_key: str = Query(default="7d", alias="range"),
    bucket: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).timeseries(range_key=range_key, bucket=bucket)


@router.get("/dashboard/distribution")
async def dashboard_distribution(
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).distribution()


@router.get("/dashboard/agent-performance")
async def dashboard_agent_performance(
    range_key: str = Query(default="7d", alias="range"),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).agent_performance(range_key=range_key)


@router.get("/dashboard/sop-funnel")
async def dashboard_sop_funnel(
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).sop_funnel()


@router.get("/dashboard/sales-rag/summary")
async def dashboard_sales_rag_summary(
    range_key: str = Query(default="7d", alias="range"),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).sales_rag_summary(range_key=range_key)


@router.get("/dashboard/sales-rag/timeseries")
async def dashboard_sales_rag_timeseries(
    range_key: str = Query(default="7d", alias="range"),
    bucket: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).sales_rag_timeseries(range_key=range_key, bucket=bucket)


@router.get("/dashboard/sales-rag/comparison")
async def dashboard_sales_rag_comparison(
    range_key: str = Query(default="7d", alias="range"),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).sales_rag_comparison(range_key=range_key)


@router.get("/dashboard/sales-rag/recent-uses")
async def dashboard_sales_rag_recent_uses(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _auth: dict[str, Any] = Depends(require_admin_auth),
) -> dict[str, Any]:
    return AdminDashboardService(db).sales_rag_recent_uses(limit=limit)
