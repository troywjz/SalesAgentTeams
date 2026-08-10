import asyncio
from pathlib import Path

from app.core.config import Settings
from app.llm.embedding import EmbeddingResponse
from evaluation.core.knowledge_snapshot import (
    SnapshotSafetyVectorReviewer,
    SnapshotSalesCaseRAGService,
    create_snapshot_knowledge_loader,
)


class _SnapshotEmbeddingClient:
    async def embed(self, text: str) -> EmbeddingResponse:
        vector = [1.0, 0.0] if any(term in text for term in ("Excel", "保证", "包过")) else [0.0, 1.0]
        return EmbeddingResponse(
            embedding=vector,
            provider="siliconflow",
            model="test-embedding",
            column_name="ignored-by-snapshot",
            raw_response={},
        )


def _settings(**overrides) -> Settings:
    values = {
        "DATABASE_URL": "postgresql+psycopg://invalid:invalid@127.0.0.1:1/must_not_connect",
        "DEMO_MODE": True,
        "SALES_RAG_ENABLED": True,
        "SAFETY_VECTOR_ENABLED": True,
        "SAFETY_VECTOR_THRESHOLD": 0.7,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_snapshot_loader_reads_files_without_formal_database(monkeypatch) -> None:
    def fail_database_access():
        raise AssertionError("评测快照不应访问正式知识数据库")

    monkeypatch.setattr("app.knowledge.loader.SessionLocal", fail_database_access)
    loader = create_snapshot_knowledge_loader()

    context = loader.query_context(message="Excel 课程零基础适合吗？", intent={}, current_stage="开场")

    assert loader.use_database is False
    assert loader.load_business_identity() == (
        Path("evaluation/knowledge_snapshot/identity.md").read_text(encoding="utf-8").strip()
    )
    assert context["skus"]
    assert "零基础可以学习吗" in context["faq"]
    assert loader.load_safety_rules()["source"] == "safety_rules_csv"


def test_snapshot_rag_and_safety_use_snapshot_files_without_database() -> None:
    loader = create_snapshot_knowledge_loader()
    embeddings = _SnapshotEmbeddingClient()
    rag = SnapshotSalesCaseRAGService(
        settings=_settings(),
        embedding_client=embeddings,
    )
    safety = SnapshotSafetyVectorReviewer(
        knowledge_loader=loader,
        settings=_settings(),
        embedding_client=embeddings,
    )

    references = asyncio.run(rag.retrieve(message="我刚开始学 Excel，怎么学？"))
    review = asyncio.run(safety.review(draft_reply="这个课程一定保证通过。"))

    assert references
    assert "Excel" in references[0].customer_text
    assert review["source_available"] is True
    assert review["action"] == "revise"
    assert review["matches"][0]["rule_id"].startswith("snapshot-safety-")
