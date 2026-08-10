from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.llm.base import LLMProviderError
from app.llm.embedding import EmbeddingClient, create_embedding_client


SALES_RAG_VECTOR_COLUMNS = {
    "siliconflow": "sales_embedding_gjld_q3e8b",
    "aliyun": "sales_embedding_albl_tev4",
}


@dataclass(frozen=True)
class SalesCaseRAGReference:
    chunk_id: str
    conversation_hash: str
    customer_text: str
    sales_reply: str
    context_before: str
    quality_score: float
    similarity: float
    tags: list[str]

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "conversation_hash": self.conversation_hash,
            "customer_text": self.customer_text,
            "sales_reply": self.sales_reply,
            "context_before": self.context_before,
            "quality_score": round(self.quality_score, 4),
            "similarity": round(self.similarity, 4),
            "tags": self.tags,
        }


class SalesCaseRAGService:
    """从销售案例向量中召回可借鉴话术，不把案例当作业务事实。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_client: EmbeddingClient | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding_client = embedding_client or create_embedding_client(self.settings)
        self.session_factory = session_factory

    async def retrieve(
        self,
        *,
        message: str,
        current_stage: str = "",
        intent: dict[str, Any] | None = None,
    ) -> list[SalesCaseRAGReference]:
        if not self.settings.sales_rag_enabled:
            return []
        query = self._query_text(
            message=message,
            current_stage=current_stage,
            intent=intent or {},
        )
        if not query.strip() or not self._has_vector_source():
            return []

        try:
            response = await self.embedding_client.embed(query)
        except LLMProviderError:
            # RAG 是增强能力，向量服务不可用时不能阻断主对话链路。
            return []

        column_name = SALES_RAG_VECTOR_COLUMNS.get(response.provider)
        if not column_name:
            return []
        with self.session_factory() as db:
            return self._match_chunks(
                db,
                embedding=response.embedding,
                column_name=column_name,
                top_k=max(1, self.settings.sales_rag_top_k),
                min_quality_score=self.settings.sales_rag_min_quality_score,
            )

    def _has_vector_source(self) -> bool:
        for column_name in SALES_RAG_VECTOR_COLUMNS.values():
            try:
                with self.session_factory() as db:
                    found = db.execute(
                        text(
                            "SELECT 1 FROM sales_rag_chunks "
                            f"WHERE {column_name} IS NOT NULL LIMIT 1"
                        )
                    ).first()
                if found is not None:
                    return True
            except SQLAlchemyError:
                # Demo 数据库可能还没有扩展列，按无向量源处理。
                continue
        return False

    def _match_chunks(
        self,
        db: Session,
        *,
        embedding: list[float],
        column_name: str,
        top_k: int,
        min_quality_score: float,
    ) -> list[SalesCaseRAGReference]:
        if column_name not in SALES_RAG_VECTOR_COLUMNS.values():
            return []
        rows = db.execute(
            text(
                f"""
                SELECT
                    chunk_id,
                    conversation_hash,
                    customer_text,
                    sales_reply,
                    context_before,
                    quality_score,
                    tags_json,
                    {column_name}::text AS embedding_text
                FROM sales_rag_chunks
                WHERE {column_name} IS NOT NULL
                  AND quality_score >= :min_quality_score
                """
            ),
            {"min_quality_score": min_quality_score},
        ).mappings().all()
        matches: list[SalesCaseRAGReference] = []
        for row in rows:
            stored_embedding = _parse_vector(row["embedding_text"])
            if not stored_embedding:
                continue
            matches.append(
                SalesCaseRAGReference(
                    chunk_id=str(row["chunk_id"]),
                    conversation_hash=str(row["conversation_hash"]),
                    customer_text=str(row["customer_text"] or ""),
                    sales_reply=str(row["sales_reply"] or ""),
                    context_before=str(row["context_before"] or ""),
                    quality_score=float(row["quality_score"] or 0.0),
                    similarity=_cosine_similarity(embedding, stored_embedding),
                    tags=_loads_list(row["tags_json"]),
                )
            )
        matches.sort(key=lambda item: (item.similarity, item.quality_score), reverse=True)
        return matches[:top_k]

    @staticmethod
    def _query_text(
        *,
        message: str,
        current_stage: str,
        intent: dict[str, Any],
    ) -> str:
        return "\n".join(
            item
            for item in (
                f"当前阶段：{current_stage}" if current_stage else "",
                f"意图：{intent.get('intent_category')}" if intent.get("intent_category") else "",
                f"意向：{intent.get('purchase_intent')}" if intent.get("purchase_intent") else "",
                f"客户消息：{message}",
            )
            if item
        )


def _parse_vector(value: str | None) -> list[float]:
    if not value:
        return []
    text_value = value.strip().strip("[]")
    if not text_value:
        return []
    try:
        return [float(item) for item in text_value.split(",") if item.strip()]
    except ValueError:
        return []


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _loads_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]
