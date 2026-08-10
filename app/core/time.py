from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def beijing_now() -> datetime:
    """返回东八区北京时间，用于面向中国业务人员展示和记录。"""
    return datetime.now(BEIJING_TZ)


def to_beijing_time(value: datetime | None) -> datetime | None:
    """把数据库或外部来源时间统一转换为东八区 aware datetime。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(BEIJING_TZ)


def to_utc_time(value: datetime) -> datetime:
    """比较时间先转 UTC，避免不同时区 offset 影响逻辑判断。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(UTC)
