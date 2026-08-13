import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.models import SalesRAGChunk
from app.llm.embedding import EmbeddingResponse
from app.sales_rag.importer import (
    SalesCaseImportError,
    index_sales_case_embeddings,
    load_sales_case_csv,
    replace_sales_cases,
)


def _write_cases(path: Path) -> Path:
    path.write_text(
        "case_id,customer_message,sales_reply,context_before,quality_score,tags\n"
        "case-1,我担心自己零基础跟不上,先确认你最常用的办公场景。,客户想提升办公效率,0.9,零基础;探需\n"
        "case-2,我工作忙没时间学,可以先按工作节奏拆成小目标。,客户有学习意向,0.8,时间;学习安排\n",
        encoding="utf-8",
    )
    return path


def test_sales_case_csv_is_a_structured_formal_source(tmp_path: Path) -> None:
    rows = load_sales_case_csv(_write_cases(tmp_path / "sales_cases.csv"))

    assert len(rows) == 2
    assert rows[0].case_id == "case-1"
    assert rows[0].quality_score == 0.9
    assert rows[0].tags == ["零基础", "探需"]

    invalid = tmp_path / "invalid.csv"
    invalid.write_text("case_id,customer_message\ncase-1,测试\n", encoding="utf-8")
    with pytest.raises(SalesCaseImportError, match="缺少列"):
        load_sales_case_csv(invalid)


class _ImportSession:
    def __init__(self) -> None:
        self.added = []
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)

    def scalars(self, _statement):
        return _ScalarResult([])

    def add(self, item):
        self.added.append(item)


def test_replace_sales_cases_stores_only_the_declared_csv_fields(tmp_path: Path) -> None:
    session = _ImportSession()

    count = replace_sales_cases(session, _write_cases(tmp_path / "sales_cases.csv"))

    chunks = [item for item in session.added if isinstance(item, SalesRAGChunk)]
    assert count == 2
    assert len(chunks) == 2
    assert chunks[0].customer_text == "我担心自己零基础跟不上"
    assert "case_id" in chunks[0].raw_json
    assert len(session.executed) == 2


def test_replace_sales_cases_reuses_vector_for_unchanged_embedding_text(
    tmp_path: Path,
) -> None:
    source = _write_cases(tmp_path / "sales_cases.csv")
    first = _ImportSession()
    replace_sales_cases(first, source)
    old_chunk = next(item for item in first.added if isinstance(item, SalesRAGChunk))
    old_chunk.sales_embedding_gjld_q3e8b = "[0.1, 0.2]"

    second = _ImportSession()
    second.scalars = lambda _statement: _ScalarResult([old_chunk])
    replace_sales_cases(second, source)

    new_chunk = next(item for item in second.added if isinstance(item, SalesRAGChunk))
    assert new_chunk.sales_embedding_gjld_q3e8b == "[0.1, 0.2]"


def test_replace_sales_cases_discards_vector_when_embedding_text_changes(
    tmp_path: Path,
) -> None:
    source = _write_cases(tmp_path / "sales_cases.csv")
    first = _ImportSession()
    replace_sales_cases(first, source)
    old_chunk = next(item for item in first.added if isinstance(item, SalesRAGChunk))
    old_chunk.sales_embedding_gjld_q3e8b = "[0.1, 0.2]"
    old_chunk.customer_text = "已变化的客户问题"

    second = _ImportSession()
    second.scalars = lambda _statement: _ScalarResult([old_chunk])
    replace_sales_cases(second, source)

    new_chunk = next(item for item in second.added if isinstance(item, SalesRAGChunk))
    assert new_chunk.sales_embedding_gjld_q3e8b is None


class _ScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _IndexSession:
    def __init__(self, chunks: dict[str, SalesRAGChunk]) -> None:
        self.chunks = chunks
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def scalars(self, _statement):
        return _ScalarResult(list(self.chunks.values()))

    def get(self, _model, chunk_id):
        return self.chunks.get(chunk_id)

    def commit(self):
        self.commits += 1


class _EmbeddingClient:
    async def embed(self, _text):
        return EmbeddingResponse(
            embedding=[0.1, 0.2],
            provider="siliconflow",
            model="TEST_ONLY",
            column_name="unused",
            raw_response={},
        )


def test_sales_case_index_uses_configured_embedding_and_persists_vector() -> None:
    chunk = SalesRAGChunk(
        chunk_id="chunk-1",
        conversation_hash="conversation-1",
        customer_text="客户问题",
        sales_reply="销售回复",
        context_before="上文",
    )
    session = _IndexSession({chunk.chunk_id: chunk})
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5432/sales_agent_demo",
        SALES_RAG_ENABLED=True,
    )

    indexed = asyncio.run(
        index_sales_case_embeddings(
            settings=settings,
            embedding_client=_EmbeddingClient(),
            session_factory=lambda: session,
        )
    )

    assert indexed == 1
    assert chunk.sales_embedding_gjld_q3e8b == "[0.1, 0.2]"
    assert session.commits == 1
