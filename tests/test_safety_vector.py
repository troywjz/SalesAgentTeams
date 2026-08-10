import asyncio

from app.core.config import Settings
from app.knowledge.safety_vector import SafetyVectorReviewer
from app.llm.embedding import EmbeddingResponse


class EmptyResult:
    def first(self):
        return None

    def mappings(self):
        return self

    def all(self):
        return []


class EmptySession:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, _statement):
        return EmptyResult()


class VectorResult:
    def __init__(self, rows=None, found=False):
        self.rows = rows or []
        self.found = found

    def first(self):
        return (1,) if self.found else None

    def mappings(self):
        return self

    def all(self):
        return self.rows


class VectorSession:
    def __init__(self):
        self.saved = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement):
        if "SELECT 1 FROM knowledge_safety_rules" in str(statement):
            return VectorResult(found=True)
        return VectorResult(
            rows=[
                {
                    "rule_id": "rule-1",
                    "level": "高",
                    "primary_category": "承诺",
                    "secondary_category": "结果",
                    "standard": "不得保证结果",
                    "violation": "一定有效",
                    "handling_result": "改写",
                    "embedding_text": "[1.0, 0.0]",
                }
            ]
        )

    def add(self, value):
        self.saved.append(value)

    def commit(self):
        return None


class FailingEmbeddingClient:
    called = False

    async def embed(self, _text):
        self.called = True
        raise AssertionError("没有向量数据时不应调用 Embedding")


class FakeEmbeddingClient:
    async def embed(self, _text):
        return EmbeddingResponse(
            embedding=[1.0, 0.0],
            provider="siliconflow",
            model="demo-embedding",
            column_name="violation_embedding_gjld_q3e8b",
            raw_response={},
        )


def test_safety_vector_without_source_returns_pass_without_embedding() -> None:
    embedding_client = FailingEmbeddingClient()
    reviewer = SafetyVectorReviewer(
        settings=Settings(
            _env_file=None,
            DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
            SAFETY_VECTOR_ENABLED=True,
        ),
        embedding_client=embedding_client,
        session_factory=EmptySession,
    )

    result = asyncio.run(reviewer.review(draft_reply="这项服务一定可以保证结果。"))

    assert result["enabled"] is True
    assert result["source_available"] is False
    assert result["action"] == "pass"
    assert embedding_client.called is False


def test_safety_vector_source_can_trigger_revision() -> None:
    session = VectorSession()
    reviewer = SafetyVectorReviewer(
        settings=Settings(
            _env_file=None,
            DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
            SAFETY_VECTOR_ENABLED=True,
        ),
        embedding_client=FakeEmbeddingClient(),
        session_factory=lambda: session,
    )

    result = asyncio.run(reviewer.review(draft_reply="一定保证结果。"))

    assert result["source_available"] is True
    assert result["action"] == "revise"
    assert result["matches"][0]["rule_id"] == "rule-1"
    assert session.saved


def test_safety_vector_replay_keeps_matching_but_skips_audit_writes() -> None:
    session = VectorSession()
    reviewer = SafetyVectorReviewer(
        settings=Settings(
            _env_file=None,
            DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
            SAFETY_VECTOR_ENABLED=True,
        ),
        embedding_client=FakeEmbeddingClient(),
        session_factory=lambda: session,
        record_runtime_events=False,
    )

    result = asyncio.run(reviewer.review(draft_reply="一定保证结果。"))

    assert result["source_available"] is True
    assert result["action"] == "revise"
    assert result["matches"][0]["rule_id"] == "rule-1"
    assert session.saved == []
