from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.time import beijing_now
from app.db.models import LLMCallEmbed, LLMSafetyVectorMatch
from app.db.session import SessionLocal
from app.llm.base import LLMProviderError
from app.llm.embedding import EmbeddingClient, create_embedding_client


SAFETY_VECTOR_COLUMNS = {
    "siliconflow": "violation_embedding_gjld_q3e8b",
    "aliyun": "violation_embedding_albl_tev4",
}


@dataclass(frozen=True)
class SafetyVectorMatch:
    rule_id: str
    level: str
    primary_category: str
    secondary_category: str
    standard: str
    violation: str
    handling_result: str
    similarity: float


class SafetyVectorReviewer:
    """使用风控规则向量召回候选规则，并将结果交给安全审核节点。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_client: EmbeddingClient | None = None,
        session_factory=SessionLocal,
        record_runtime_events: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding_client = embedding_client or create_embedding_client(self.settings)
        self.session_factory = session_factory
        # 评估回放可关闭审计写入，但仍执行同一向量召回和风险判定。
        self.record_runtime_events = record_runtime_events

    async def review(
        self,
        *,
        draft_reply: str,
        session_id: str = "",
        turn_id: str = "",
        node_invocation_id: str = "",
        node_name: str = "safety",
    ) -> dict[str, Any]:
        if not self.settings.safety_vector_enabled:
            return {"enabled": False, "source_available": False, "matches": []}

        text_value = draft_reply.strip()
        if not text_value:
            return {
                "enabled": True,
                "source_available": False,
                "action": "pass",
                "matches": [],
            }

        # 先检查规则表是否真的存在向量数据。没有数据时只走 SafetyAgent，
        # 不创建 Embedding 请求，也不因本地 Demo 缺少向量服务而报错。
        if not self._has_vector_source():
            return {
                "enabled": True,
                "source_available": False,
                "action": "pass",
                "matches": [],
            }

        try:
            response = await self.embedding_client.embed(text_value)
        except LLMProviderError as exc:
            if self.record_runtime_events:
                with self.session_factory() as db:
                    self._save_embedding_calls(
                        db,
                        session_id=session_id,
                        turn_id=turn_id,
                        node_invocation_id=node_invocation_id,
                        node_name=node_name,
                        target_table="runtime_reply",
                        target_column="",
                        target_id=session_id,
                        calls=list(getattr(exc, "call_attempts", []) or []),
                    )
                    db.commit()
            raise

        threshold = self.settings.safety_vector_threshold
        with self.session_factory() as db:
            if self.record_runtime_events:
                self._save_embedding_calls(
                    db,
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=node_invocation_id,
                    node_name=node_name,
                    target_table="runtime_reply",
                    target_column=response.column_name,
                    target_id=session_id,
                    calls=response.call_attempts,
                )
            matches = self._match_rules(
                db,
                embedding=response.embedding,
                column_name=response.column_name,
                top_k=max(1, self.settings.safety_vector_top_k),
            )
            action = "revise" if any(match.similarity >= threshold for match in matches) else "pass"
            if self.record_runtime_events:
                self._save_vector_matches(
                    db,
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=node_invocation_id,
                    node_name=node_name,
                    provider=response.provider,
                    model=response.model,
                    target_column=response.column_name,
                    draft_reply=text_value,
                    threshold=threshold,
                    action=action,
                    matches=matches,
                )
                db.commit()

        risky_matches = [match for match in matches if match.similarity >= threshold]
        if not risky_matches:
            return {
                "enabled": True,
                "source_available": True,
                "action": "pass",
                "provider": response.provider,
                "model": response.model,
                "threshold": threshold,
                "matches": [_match_dict(match) for match in matches],
            }

        risks = [
            {
                "rule_id": match.rule_id,
                "level": match.level,
                "category": f"{match.primary_category}/{match.secondary_category}".strip("/"),
                "reason": match.standard or match.violation,
                "violation": match.violation,
                "handling_result": match.handling_result,
                "similarity": round(match.similarity, 4),
            }
            for match in risky_matches
        ]
        return {
            "enabled": True,
            "source_available": True,
            "action": "revise",
            "provider": response.provider,
            "model": response.model,
            "threshold": threshold,
            "risks": risks,
            "matches": [_match_dict(match) for match in matches],
        }

    def _has_vector_source(self) -> bool:
        for column_name in SAFETY_VECTOR_COLUMNS.values():
            try:
                with self.session_factory() as db:
                    found = db.execute(
                        text(
                            "SELECT 1 FROM knowledge_safety_rules "
                            f"WHERE {column_name} IS NOT NULL LIMIT 1"
                        )
                    ).first()
                if found is not None:
                    return True
            except SQLAlchemyError:
                # 老的 Demo 数据库可能尚未完成 schema 补齐，按无向量源处理。
                continue
        return False

    def _match_rules(
        self,
        db: Session,
        *,
        embedding: list[float],
        column_name: str,
        top_k: int,
    ) -> list[SafetyVectorMatch]:
        if column_name not in SAFETY_VECTOR_COLUMNS.values():
            return []
        sql = text(
            f"""
            SELECT
                rule_id,
                level,
                primary_category,
                secondary_category,
                standard,
                violation,
                handling_result,
                {column_name}::text AS embedding_text
            FROM knowledge_safety_rules
            WHERE {column_name} IS NOT NULL
            """
        )
        rows = db.execute(sql).mappings().all()
        matches: list[SafetyVectorMatch] = []
        for row in rows:
            rule_embedding = _parse_vector(row["embedding_text"])
            if not rule_embedding:
                continue
            matches.append(
                SafetyVectorMatch(
                    rule_id=str(row["rule_id"]),
                    level=str(row["level"] or ""),
                    primary_category=str(row["primary_category"] or ""),
                    secondary_category=str(row["secondary_category"] or ""),
                    standard=str(row["standard"] or ""),
                    violation=str(row["violation"] or ""),
                    handling_result=str(row["handling_result"] or ""),
                    similarity=_cosine_similarity(embedding, rule_embedding),
                )
            )
        matches.sort(key=lambda item: item.similarity, reverse=True)
        return matches[:top_k]

    def _save_embedding_calls(
        self,
        db: Session,
        *,
        session_id: str,
        turn_id: str,
        node_invocation_id: str,
        node_name: str,
        target_table: str,
        target_column: str,
        target_id: str,
        calls: list[Any],
    ) -> None:
        for call in calls:
            db.add(
                LLMCallEmbed(
                    call_id=str(uuid4()),
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=node_invocation_id,
                    node_name=node_name,
                    provider=call.provider,
                    model_name=call.model,
                    api_url=call.api_url,
                    target_table=target_table,
                    target_column=target_column,
                    target_id=target_id,
                    attempt_index=call.attempt_index,
                    elapsed_ms=call.elapsed_ms,
                    success=1 if call.success else 0,
                    embedding_dimension=call.embedding_dimension,
                    input_text=call.input_text,
                    error_type=call.error_type,
                    error_message=call.error_message,
                    request_json=json.dumps(call.request_json, ensure_ascii=False),
                    response_json=json.dumps(call.response_json, ensure_ascii=False),
                    usage_json=json.dumps(call.usage, ensure_ascii=False),
                    created_at=beijing_now(),
                )
            )

    def _save_vector_matches(
        self,
        db: Session,
        *,
        session_id: str,
        turn_id: str,
        node_invocation_id: str,
        node_name: str,
        provider: str,
        model: str,
        target_column: str,
        draft_reply: str,
        threshold: float,
        action: str,
        matches: list[SafetyVectorMatch],
    ) -> None:
        for index, match in enumerate(matches, start=1):
            db.add(
                LLMSafetyVectorMatch(
                    match_id=str(uuid4()),
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=node_invocation_id,
                    node_name=node_name,
                    provider=provider,
                    model_name=model,
                    target_table="knowledge_safety_rules",
                    target_column=target_column,
                    target_id=match.rule_id,
                    rule_id=match.rule_id,
                    level=match.level,
                    primary_category=match.primary_category,
                    secondary_category=match.secondary_category,
                    standard=match.standard,
                    violation=match.violation,
                    handling_result=match.handling_result,
                    draft_reply=draft_reply,
                    similarity=match.similarity,
                    threshold=threshold,
                    match_rank=index,
                    is_hit=1 if match.similarity >= threshold else 0,
                    action=action,
                    created_at=beijing_now(),
                )
            )


def _parse_vector(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    text_value = str(value).strip()
    if text_value.startswith("[") and text_value.endswith("]"):
        text_value = text_value[1:-1]
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


def _match_dict(match: SafetyVectorMatch) -> dict[str, Any]:
    return {
        "rule_id": match.rule_id,
        "level": match.level,
        "primary_category": match.primary_category,
        "secondary_category": match.secondary_category,
        "standard": match.standard,
        "violation": match.violation,
        "handling_result": match.handling_result,
        "similarity": round(match.similarity, 4),
    }
