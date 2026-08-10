from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.db.models import SalesRAGChunk, SalesRAGConversation
from app.db.session import SessionLocal
from app.llm.embedding import EmbeddingClient, create_embedding_client
from app.sales_rag.service import SALES_RAG_VECTOR_COLUMNS


class SalesCaseImportError(ValueError):
    """销售案例 CSV 不符合正式 RAG 数据契约。"""


@dataclass(frozen=True)
class SalesCaseRow:
    case_id: str
    customer_message: str
    sales_reply: str
    context_before: str
    quality_score: float
    tags: list[str]


def load_sales_case_csv(path: Path | str) -> list[SalesCaseRow]:
    """读取正式 RAG 案例 CSV；每行是一段可检索的客户问题与销售回复。"""

    source_path = Path(path)
    try:
        file = source_path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise SalesCaseImportError(f"销售案例文件不存在：{source_path}") from exc

    with file:
        reader = csv.DictReader(file)
        headers = {str(name or "").strip() for name in (reader.fieldnames or [])}
        missing = {
            "case_id",
            "customer_message",
            "sales_reply",
        } - headers
        if missing:
            raise SalesCaseImportError(
                "sales_cases.csv 缺少列：" + "、".join(sorted(missing))
            )

        rows: list[SalesCaseRow] = []
        seen_case_ids: set[str] = set()
        for line_number, raw in enumerate(reader, start=2):
            case_id = _text(raw.get("case_id"))
            customer_message = _text(raw.get("customer_message"))
            sales_reply = _text(raw.get("sales_reply"))
            if not case_id or not customer_message or not sales_reply:
                raise SalesCaseImportError(
                    f"sales_cases.csv 第 {line_number} 行必须填写 case_id、customer_message、sales_reply。"
                )
            if case_id in seen_case_ids:
                raise SalesCaseImportError(
                    f"sales_cases.csv 存在重复 case_id：{case_id}"
                )
            seen_case_ids.add(case_id)
            quality_score = _quality_score(raw.get("quality_score"), line_number)
            rows.append(
                SalesCaseRow(
                    case_id=case_id,
                    customer_message=customer_message,
                    sales_reply=sales_reply,
                    context_before=_text(raw.get("context_before")),
                    quality_score=quality_score,
                    tags=_split_tags(raw.get("tags")),
                )
            )

    if not rows:
        raise SalesCaseImportError("sales_cases.csv 没有可导入的案例。")
    return rows


def replace_sales_cases(
    db: Session,
    path: Path | str | None,
) -> int:
    """以一个 CSV 完整替换正式 RAG 案例；调用方负责事务提交。"""

    if path is None:
        return 0
    source_path = Path(path)
    rows = load_sales_case_csv(source_path)
    source_name = source_path.stem
    source_reference = _source_reference(source_path)

    db.execute(delete(SalesRAGChunk))
    db.execute(delete(SalesRAGConversation))
    for index, row in enumerate(rows, start=1):
        conversation_hash = _hash_value(f"{source_reference}:{row.case_id}")
        chunk_id = _hash_value(f"{conversation_hash}:1")
        normalized = {
            "case_id": row.case_id,
            "customer_message": row.customer_message,
            "sales_reply": row.sales_reply,
            "context_before": row.context_before,
            "quality_score": row.quality_score,
            "tags": row.tags,
        }
        db.add(
            SalesRAGConversation(
                conversation_hash=conversation_hash,
                source_name=source_name,
                source_path=source_reference,
                source_sheet="",
                raw_conversation_id=row.case_id,
                message_count=2,
                text_message_count=2,
                usable_chunk_count=1,
                quality_score=row.quality_score,
                metadata_json=json.dumps({"case_id": row.case_id}, ensure_ascii=False),
            )
        )
        db.add(
            SalesRAGChunk(
                chunk_id=chunk_id,
                conversation_hash=conversation_hash,
                chunk_index=index,
                source_name=source_name,
                customer_text=row.customer_message,
                sales_reply=row.sales_reply,
                context_before=row.context_before,
                chunk_text=_chunk_text(row),
                quality_score=row.quality_score,
                tags_json=json.dumps(row.tags, ensure_ascii=False),
                # 不保留源 CSV 的未识别列，避免把无关个人信息带入 RAG 数据库。
                raw_json=json.dumps(normalized, ensure_ascii=False),
            )
        )
    return len(rows)


async def index_sales_case_embeddings(
    *,
    settings: Settings | None = None,
    embedding_client: EmbeddingClient | None = None,
    session_factory=SessionLocal,
) -> int:
    """为尚无向量的正式案例建立索引；只在 SALES_RAG_ENABLED=true 时执行。"""

    runtime_settings = settings or get_settings()
    if not runtime_settings.sales_rag_enabled:
        return 0
    client = embedding_client or create_embedding_client(runtime_settings)
    with session_factory() as db:
        candidates = [
            (chunk.chunk_id, _embedding_text(chunk))
            for chunk in db.scalars(select(SalesRAGChunk).order_by(SalesRAGChunk.chunk_index)).all()
            if not _has_any_vector(chunk)
        ]

    indexed = 0
    for chunk_id, text_value in candidates:
        response = await client.embed(text_value)
        target_column = SALES_RAG_VECTOR_COLUMNS.get(response.provider)
        if target_column is None:
            continue
        with session_factory() as db:
            chunk = db.get(SalesRAGChunk, chunk_id)
            if chunk is None or _has_any_vector(chunk):
                continue
            setattr(chunk, target_column, json.dumps(response.embedding))
            db.commit()
            indexed += 1
    return indexed


def index_sales_case_embeddings_sync(
    *,
    settings: Settings | None = None,
) -> int:
    """供正式启动/导入流程调用的同步包装；不能在已运行的事件循环中使用。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(index_sales_case_embeddings(settings=settings))
    raise RuntimeError("销售案例向量索引必须在同步启动或独立脚本中运行。")


def _embedding_text(chunk: SalesRAGChunk) -> str:
    return "\n".join(
        value
        for value in (
            f"上文：{chunk.context_before}" if chunk.context_before else "",
            f"客户：{chunk.customer_text}",
        )
        if value
    )


def _chunk_text(row: SalesCaseRow) -> str:
    return "\n".join(
        value
        for value in (
            f"上文：{row.context_before}" if row.context_before else "",
            f"客户：{row.customer_message}",
            f"销售：{row.sales_reply}",
        )
        if value
    )


def _has_any_vector(chunk: SalesRAGChunk) -> bool:
    return any(
        bool(getattr(chunk, column_name, None))
        for column_name in SALES_RAG_VECTOR_COLUMNS.values()
    )


def _quality_score(value: Any, line_number: int) -> float:
    text = _text(value)
    if not text:
        return 1.0
    try:
        score = float(text)
    except ValueError as exc:
        raise SalesCaseImportError(
            f"sales_cases.csv 第 {line_number} 行 quality_score 必须是 0 到 1 的数字。"
        ) from exc
    if not 0 <= score <= 1:
        raise SalesCaseImportError(
            f"sales_cases.csv 第 {line_number} 行 quality_score 必须在 0 到 1 之间。"
        )
    return score


def _split_tags(value: Any) -> list[str]:
    return [item.strip() for item in re.split(r"[;；,，、\n]", _text(value)) if item.strip()]


def _source_reference(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()
