from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.knowledge import KnowledgeLoader
from app.knowledge.safety_vector import SafetyVectorMatch, _cosine_similarity, _match_dict
from app.llm.base import LLMProviderError
from app.llm.embedding import EmbeddingClient, create_embedding_client
from app.sales_rag.importer import SalesCaseRow, load_sales_case_csv
from app.sales_rag.service import SalesCaseRAGReference, SalesCaseRAGService


# 评测知识快照与正式 data/ 目录隔离；文件名保持与正式私有源一致。
KNOWLEDGE_SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "knowledge_snapshot"


def create_snapshot_knowledge_loader() -> KnowledgeLoader:
    """创建只读取评测快照文件、绝不访问正式知识数据库的加载器。"""

    return KnowledgeLoader(
        KNOWLEDGE_SNAPSHOT_DIR,
        business_dir=KNOWLEDGE_SNAPSHOT_DIR,
        use_database=False,
    )


class SnapshotSalesCaseRAGService:
    """在内存中检索评测快照案例，不读取或写入正式 RAG 表。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_client: EmbeddingClient | None = None,
        snapshot_dir: Path | str = KNOWLEDGE_SNAPSHOT_DIR,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding_client = embedding_client or create_embedding_client(self.settings)
        self.snapshot_dir = Path(snapshot_dir)
        self.rows = load_sales_case_csv(self.snapshot_dir / "sales_cases.csv")
        self._vectors_by_provider: dict[str, dict[str, list[float]]] = {}
        self._vector_lock = asyncio.Lock()

    async def retrieve(
        self,
        *,
        message: str,
        current_stage: str = "",
        intent: dict[str, Any] | None = None,
    ) -> list[SalesCaseRAGReference]:
        if not self.settings.sales_rag_enabled:
            return []
        query = SalesCaseRAGService._query_text(
            message=message,
            current_stage=current_stage,
            intent=intent or {},
        )
        if not query.strip():
            return []
        try:
            response = await self.embedding_client.embed(query)
        except LLMProviderError:
            return []

        vectors = await self._vectors_for_provider(response.provider)
        matches = [
            SalesCaseRAGReference(
                chunk_id=_snapshot_id("sales-case", row.case_id),
                conversation_hash=_snapshot_id("sales-conversation", row.case_id),
                customer_text=row.customer_message,
                sales_reply=row.sales_reply,
                context_before=row.context_before,
                quality_score=row.quality_score,
                similarity=_cosine_similarity(response.embedding, vectors[row.case_id]),
                tags=row.tags,
            )
            for row in self.rows
            if row.case_id in vectors
            and row.quality_score >= self.settings.sales_rag_min_quality_score
        ]
        matches.sort(key=lambda item: (item.similarity, item.quality_score), reverse=True)
        return matches[: max(1, self.settings.sales_rag_top_k)]

    async def _vectors_for_provider(self, provider: str) -> dict[str, list[float]]:
        async with self._vector_lock:
            if provider in self._vectors_by_provider:
                return self._vectors_by_provider[provider]
            vectors: dict[str, list[float]] = {}
            for row in self.rows:
                try:
                    response = await self.embedding_client.embed(_sales_case_embedding_text(row))
                except LLMProviderError:
                    continue
                if response.provider == provider:
                    vectors[row.case_id] = response.embedding
            self._vectors_by_provider[provider] = vectors
            return vectors


class SnapshotSafetyVectorReviewer:
    """在内存中审核评测快照的风控规则，不读取或写入正式数据库。"""

    def __init__(
        self,
        *,
        knowledge_loader: KnowledgeLoader,
        settings: Settings | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding_client = embedding_client or create_embedding_client(self.settings)
        self.rules = list((knowledge_loader.load_safety_rules() or {}).get("rules") or [])
        self._vectors_by_provider: dict[str, dict[str, list[float]]] = {}
        self._vector_lock = asyncio.Lock()

    async def review(
        self,
        *,
        draft_reply: str,
        **_: Any,
    ) -> dict[str, Any]:
        if not self.settings.safety_vector_enabled:
            return {"enabled": False, "source_available": False, "matches": []}
        text_value = draft_reply.strip()
        if not text_value or not self.rules:
            return {
                "enabled": True,
                "source_available": False,
                "action": "pass",
                "matches": [],
            }
        try:
            response = await self.embedding_client.embed(text_value)
        except LLMProviderError:
            raise

        vectors = await self._vectors_for_provider(response.provider)
        snapshot_rules = _snapshot_rules(self.rules)
        matches = [
            _safety_match(rule_id, rule, vectors[rule_id], response.embedding)
            for rule_id, rule in snapshot_rules.items()
            if rule_id in vectors
        ]
        matches.sort(key=lambda item: item.similarity, reverse=True)
        matches = matches[: max(1, self.settings.safety_vector_top_k)]
        threshold = self.settings.safety_vector_threshold
        risky_matches = [match for match in matches if match.similarity >= threshold]
        payload: dict[str, Any] = {
            "enabled": True,
            "source_available": bool(vectors),
            "provider": response.provider,
            "model": response.model,
            "threshold": threshold,
            "matches": [_match_dict(match) for match in matches],
        }
        if not risky_matches:
            return {**payload, "action": "pass"}
        return {
            **payload,
            "action": "revise",
            "risks": [
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
            ],
        }

    async def _vectors_for_provider(self, provider: str) -> dict[str, list[float]]:
        async with self._vector_lock:
            if provider in self._vectors_by_provider:
                return self._vectors_by_provider[provider]
            vectors: dict[str, list[float]] = {}
            for rule_id, rule in _snapshot_rules(self.rules).items():
                try:
                    response = await self.embedding_client.embed(_safety_embedding_text(rule))
                except LLMProviderError:
                    continue
                if response.provider == provider:
                    vectors[rule_id] = response.embedding
            self._vectors_by_provider[provider] = vectors
            return vectors


def _sales_case_embedding_text(row: SalesCaseRow) -> str:
    return "\n".join(
        value
        for value in (
            f"上文：{row.context_before}" if row.context_before else "",
            f"客户：{row.customer_message}",
        )
        if value
    )


def _snapshot_rules(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        f"snapshot-safety-{index:03d}": rule
        for index, rule in enumerate(rules, start=1)
    }


def _safety_embedding_text(rule: dict[str, Any]) -> str:
    return "\n".join(
        value
        for value in (
            f"标准：{rule.get('standard', '')}",
            f"违规：{rule.get('violation', '')}",
        )
        if value.strip("：")
    )


def _safety_match(
    rule_id: str,
    rule: dict[str, Any],
    rule_embedding: list[float],
    reply_embedding: list[float],
) -> SafetyVectorMatch:
    return SafetyVectorMatch(
        rule_id=rule_id,
        level=str(rule.get("level") or ""),
        primary_category=str(rule.get("primary_category") or ""),
        secondary_category=str(rule.get("secondary_category") or ""),
        standard=str(rule.get("standard") or ""),
        violation=str(rule.get("violation") or ""),
        handling_result=str(rule.get("handling_result") or ""),
        similarity=_cosine_similarity(reply_embedding, rule_embedding),
    )


def _snapshot_id(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()
