from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.time import beijing_now


def utc_now() -> datetime:
    return beijing_now()


class CustomerProfile(BaseModel):
    name: str = ""
    age: str = ""
    education: str = ""
    work_status: str = ""
    learning_goal: str = ""
    budget: str = ""
    urgency: str = ""
    concerns: list[str] = Field(default_factory=list)
    purchase_intent: str = "low"


class ConversationState(BaseModel):
    """会话状态：字段全部平铺，不再嵌套大对象。

    持久化时各字段写入数据库独立列（conversation_sessions + list_customer）。
    """
    session_id: str
    customer_id: str = ""
    current_stage: str = "开场"
    customer_profile: CustomerProfile = Field(default_factory=CustomerProfile)
    history_summary: str = ""
    message_count: int = 0
    transfer_flag: bool = False
    transfer_reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()
