from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


settings = get_settings()
database_url = settings.database_url
if not database_url.startswith("postgresql+"):
    raise RuntimeError("Windows Demo 继续使用 PostgreSQL，请检查 DATABASE_URL。")
database_name = (make_url(database_url).database or "").lower()
if database_name != "sales_agent_demo":
    raise RuntimeError(
        "Windows Demo 只能连接独立数据库 sales_agent_demo，禁止连接 Linux 生产数据库。"
    )

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@event.listens_for(engine, "connect")
def _configure_postgres_connection(dbapi_connection, _connection_record) -> None:
    """统一按北京时间展示 PostgreSQL 的时区字段。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'Asia/Shanghai'")
    cursor.close()


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_demo_schema_compatibility()


def _ensure_demo_schema_compatibility() -> None:
    """为已有 Demo 数据库补齐向量列，避免 create_all 漏掉后续新增列。"""
    vector_columns = (
        (
            "knowledge_safety_rules",
            "violation_embedding_gjld_q3e8b",
        ),
        (
            "knowledge_safety_rules",
            "violation_embedding_albl_tev4",
        ),
        (
            "sales_rag_chunks",
            "sales_embedding_gjld_q3e8b",
        ),
        (
            "sales_rag_chunks",
            "sales_embedding_albl_tev4",
        ),
    )
    with engine.begin() as connection:
        for table_name, column_name in vector_columns:
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN IF NOT EXISTS {column_name} TEXT"
                )
            )


def get_db_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
