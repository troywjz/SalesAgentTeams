from __future__ import annotations

import re
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings


def ensure_postgres_database() -> None:
    """确保演示数据库存在，但绝不自动创建非 Demo 名称的数据库。"""
    settings = get_settings()
    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("Windows Demo 仅支持 PostgreSQL。")

    database_name = database_url.database or ""
    if not database_name:
        raise RuntimeError("DATABASE_URL 缺少 PostgreSQL 数据库名。")

    connect_args = {"connect_timeout": settings.database_connect_timeout_seconds}
    target_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    try:
        with target_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print(f"PostgreSQL database is ready: {database_name}")
        return
    except OperationalError:
        pass
    finally:
        target_engine.dispose()

    if database_name.lower() != "sales_agent_demo":
        raise RuntimeError(
            "目标 PostgreSQL 数据库不存在；Windows Demo 只允许自动创建 sales_agent_demo。"
        )
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise RuntimeError("演示数据库名只能包含字母、数字和下划线。")

    admin_url = database_url.set(database="postgres")
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            )
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin_engine.dispose()

    print(f"PostgreSQL demo database is ready: {database_name}")


if __name__ == "__main__":
    ensure_postgres_database()
