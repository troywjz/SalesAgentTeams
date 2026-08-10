import asyncio
import json

from app.core.config import Settings
from app.llm.embedding import EmbeddingResponse
from app.sales_rag.service import SalesCaseRAGService


class FakeResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows, source_exists=True) -> None:
        self.rows = rows
        self.source_exists = source_exists

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, _params=None):
        if "SELECT 1 FROM sales_rag_chunks" in str(statement):
            return FakeResult([(1,)] if self.source_exists else [])
        return FakeResult(self.rows)


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.called = False

    async def embed(self, text: str) -> EmbeddingResponse:
        self.called = True
        return EmbeddingResponse(
            embedding=[1.0, 0.0],
            provider="siliconflow",
            model="demo-embedding",
            column_name="violation_embedding_gjld_q3e8b",
            raw_response={"data": [{"embedding": [1.0, 0.0]}]},
        )


def _settings(enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
        SALES_RAG_ENABLED=enabled,
    )


def test_sales_rag_prefers_matching_vector_case() -> None:
    rows = [
        {
            "chunk_id": "price-case",
            "conversation_hash": "demo",
            "customer_text": "价格有点高，预算不够",
            "sales_reply": "先判断方案是否解决当前问题，再讨论投入。",
            "context_before": "客户认可需求但关注预算",
            "quality_score": 0.9,
            "tags_json": json.dumps(["价格", "预算"], ensure_ascii=False),
            "embedding_text": "[1.0, 0.0]",
        },
        {
            "chunk_id": "time-case",
            "conversation_hash": "demo",
            "customer_text": "最近工作忙，没有时间",
            "sales_reply": "可以拆成小任务。",
            "context_before": "客户担心时间投入",
            "quality_score": 0.92,
            "tags_json": json.dumps(["时间"], ensure_ascii=False),
            "embedding_text": "[0.0, 1.0]",
        },
    ]
    embedding_client = FakeEmbeddingClient()
    service = SalesCaseRAGService(
        settings=_settings(),
        embedding_client=embedding_client,
        session_factory=lambda: FakeSession(rows),
    )

    references = asyncio.run(
        service.retrieve(message="我觉得价格有点高，预算有限", current_stage="价值塑造")
    )

    assert references
    assert references[0].chunk_id == "price-case"
    assert references[0].similarity == 1.0
    assert embedding_client.called is True


def test_sales_rag_without_vector_source_does_not_embed() -> None:
    embedding_client = FakeEmbeddingClient()
    service = SalesCaseRAGService(
        settings=_settings(),
        embedding_client=embedding_client,
        session_factory=lambda: FakeSession([], source_exists=False),
    )

    assert asyncio.run(service.retrieve(message="价格是多少")) == []
    assert embedding_client.called is False


def test_disabled_sales_rag_does_not_open_database_session() -> None:
    def fail_session():
        raise AssertionError("disabled RAG should not access PostgreSQL")

    service = SalesCaseRAGService(
        settings=_settings(enabled=False),
        session_factory=fail_session,
    )

    assert asyncio.run(service.retrieve(message="价格是多少")) == []
