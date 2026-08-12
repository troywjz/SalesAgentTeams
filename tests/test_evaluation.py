import asyncio
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.knowledge import KnowledgeLoader
from app.llm import DemoLLMClient
from app.llm.base import ChatMessage, LLMProviderError, LLMResponse
from evaluation.core.csv_logger import read_csv, write_csv
from evaluation.core.dataset import (
    BLIND_MAPPING_FILENAME,
    BLIND_REVIEW_FILENAME,
    INPUT_COLUMNS,
    SYSTEM_REPLY_COLUMN,
    SYSTEM_RESULTS_FILENAME,
    EvaluationCsvDataset,
    EvaluationDatasetError,
)
from evaluation.core.scoring import (
    CANDIDATE_A,
    CANDIDATE_B,
    HUMAN_SOURCE,
    LABELS,
    SYSTEM_SOURCE,
    score_blind_review,
)
from evaluation.run import (
    _parse_memory_summary,
    create_production_replay_service,
    run_evaluation,
)


# 本文件中的 TEST_ONLY 内容只验证 CSV 回放，不是业务数据或业务结论。
def _write_input_csv(root: Path, *, rows: list[dict[str, str]] | None = None) -> Path:
    path = root / "test-only-evaluation.csv"
    values = rows or [
        {
            "来源": "TEST_TURN_001",
            "用户消息": "这个课程适合零基础吗？",
            "销售回复": "TEST_ONLY 真人回复第一条\nTEST_ONLY 真人回复第二条",
            "上文记忆": "TEST_ONLY 客户想提升办公效率。",
        },
        {
            "来源": "TEST_TURN_002",
            "用户消息": "我想了解价格和学习安排。",
            "销售回复": "TEST_ONLY 真人回复。",
            "上文记忆": "TEST_ONLY 客户在比较课程方案。",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=INPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(values)
    return path


def _settings(**overrides) -> Settings:
    values = {
        "DATABASE_URL": "postgresql+psycopg://invalid:invalid@127.0.0.1:1/must_not_connect",
        "DEMO_MODE": True,
        "DEMO_AGENT_DELAY_MS": 0,
        "CHAT_REQUEST_TIMEOUT_SECONDS": 5,
        "EVALUATION_MAX_CONCURRENCY": 2,
        "SALES_RAG_ENABLED": False,
        "SAFETY_VECTOR_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class _ReadOnlyScalarResult:
    def first(self):
        return None

    def all(self):
        return []


class _ReadOnlyKnowledgeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def scalars(self, _statement):
        return _ReadOnlyScalarResult()


def test_parse_memory_summary_extracts_history_and_profile() -> None:
    memory = (
        '{"history_summary":"客户已咨询价格",'
        '"customer_profile":{"age":"30","purchase_intent":"已报名（办公效率综合训练营，已交100元定金）"},'
        '"profile_updates":[]}'
    )

    history, profile = _parse_memory_summary(memory)

    assert history == "客户已咨询价格"
    assert profile.age == "30"
    assert profile.purchase_intent == "已报名（办公效率综合训练营，已交100元定金）"


def test_parse_memory_summary_falls_back_to_raw_text_when_not_json() -> None:
    history, profile = _parse_memory_summary("TEST_ONLY 非 JSON 文本")

    assert history == "TEST_ONLY 非 JSON 文本"
    assert profile.purchase_intent == "low"


def test_parse_memory_summary_handles_empty_string() -> None:
    history, profile = _parse_memory_summary("")

    assert history == ""
    assert profile.purchase_intent == "low"


def test_parse_memory_summary_falls_back_when_profile_is_not_dict() -> None:
    memory = '{"history_summary":"摘要","customer_profile":"已报名"}'

    history, profile = _parse_memory_summary(memory)

    assert history == "摘要"
    assert profile.purchase_intent == "low"


def test_parse_memory_summary_keeps_raw_text_when_history_missing() -> None:
    memory = '{"customer_profile":{"purchase_intent":"已报名"}}'

    history, profile = _parse_memory_summary(memory)

    assert history == memory
    assert profile.purchase_intent == "已报名"


def test_csv_dataset_requires_the_declared_first_four_columns(tmp_path: Path) -> None:
    source = _write_input_csv(tmp_path)
    dataset = EvaluationCsvDataset.load(source)

    assert dataset.fieldnames == INPUT_COLUMNS
    assert len(dataset.rows) == 2
    assert dataset.rows[0].human_sales_reply.count("\n") == 1
    assert dataset.result_fieldnames == (*INPUT_COLUMNS, SYSTEM_REPLY_COLUMN)

    invalid = tmp_path / "invalid.csv"
    invalid.write_text("用户消息,来源\n测试,TURN\n", encoding="utf-8")
    with pytest.raises(EvaluationDatasetError, match="前四列必须"):
        EvaluationCsvDataset.load(invalid)

    non_utf8 = tmp_path / "non-utf8.csv"
    non_utf8.write_bytes("来源".encode("gbk"))
    with pytest.raises(EvaluationDatasetError, match="UTF-8"):
        EvaluationCsvDataset.load(non_utf8)


def test_replay_service_reuses_production_defaults() -> None:
    settings = _settings(CHAT_REQUEST_TIMEOUT_SECONDS=37)
    service, session_store = create_production_replay_service(DemoLLMClient(delay_ms=0), settings)

    assert service.repository is None
    assert service.session_store is session_store
    assert isinstance(service.knowledge_loader, KnowledgeLoader)
    assert service.request_timeout_seconds == 37


def test_runner_outputs_five_column_result_and_blind_review_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_input_csv(tmp_path)
    monkeypatch.setattr("app.knowledge.loader.SessionLocal", _ReadOnlyKnowledgeSession)

    summary = asyncio.run(
        run_evaluation(
            source,
            output_root=tmp_path / "runs",
            settings=_settings(),
            llm_client=DemoLLMClient(delay_ms=0),
            run_id="test-only-run",
        )
    )

    assert summary.turns_total == 2
    assert summary.turns_succeeded == 2
    assert summary.turns_handed_off == 0
    assert summary.turns_failed == 0
    assert summary.max_concurrency == 2
    assert summary.results_path.name == SYSTEM_RESULTS_FILENAME
    result_columns, result_rows = read_csv(summary.results_path)
    assert result_columns == (*INPUT_COLUMNS, SYSTEM_REPLY_COLUMN)
    assert result_rows[0]["销售回复"] == "TEST_ONLY 真人回复第一条\nTEST_ONLY 真人回复第二条"
    assert result_rows[0][SYSTEM_REPLY_COLUMN]
    assert summary.blind_review_path.name == BLIND_REVIEW_FILENAME
    assert summary.blind_mapping_path.name == BLIND_MAPPING_FILENAME

    blind_columns, blind_rows = read_csv(summary.blind_review_path)
    mapping_columns, mapping_rows = read_csv(summary.blind_mapping_path)
    # 盲评表第一列沿用输入“来源”回合标识，但不能泄露真人/系统的候选来源映射。
    assert "候选甲来源" not in blind_columns
    assert "候选乙来源" not in blind_columns
    assert len(blind_rows) == len(result_rows)
    assert len(mapping_rows) == len(result_rows)
    assert any(HUMAN_SOURCE in value for row in mapping_rows for value in row.values())
    assert any(SYSTEM_SOURCE in value for row in mapping_rows for value in row.values())


def test_runner_respects_env_configured_parallelism(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_input_csv(
        tmp_path,
        rows=[
            {
                "来源": f"TEST_TURN_{index}",
                "用户消息": "TEST_ONLY",
                "销售回复": "TEST_ONLY",
                "上文记忆": "TEST_ONLY",
            }
            for index in range(3)
        ],
    )
    active = 0
    max_active = 0

    class _Store:
        def save(self, state):
            return state

    class _SlowService:
        async def process_message(self, *_args, **_kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.03)
            active -= 1
            return SimpleNamespace(
                reply="TEST_ONLY 系统回复",
                state=SimpleNamespace(transfer_flag=False, transfer_reason=""),
                agent_runs=[],
            )

    monkeypatch.setattr(
        "evaluation.run.create_production_replay_service",
        lambda *_args, **_kwargs: (_SlowService(), _Store()),
    )
    asyncio.run(
        run_evaluation(
            source,
            output_root=tmp_path / "runs",
            settings=_settings(EVALUATION_MAX_CONCURRENCY=2),
            llm_client=DemoLLMClient(delay_ms=0),
            run_id="parallel-run",
        )
    )
    assert max_active == 2


def test_blind_scoring_maps_candidates_back_to_human_and_system(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_input_csv(tmp_path)
    monkeypatch.setattr("app.knowledge.loader.SessionLocal", _ReadOnlyKnowledgeSession)
    summary = asyncio.run(
        run_evaluation(
            source,
            output_root=tmp_path / "runs",
            settings=_settings(),
            llm_client=DemoLLMClient(delay_ms=0),
            run_id="score-run",
        )
    )
    columns, reviews = read_csv(summary.blind_review_path)
    _, mappings = read_csv(summary.blind_mapping_path)
    mapping_by_id = {row["来源"]: row for row in mappings}
    for review in reviews:
        review["评审人"] = "TEST_REVIEWER"
        for candidate in (CANDIDATE_A, CANDIDATE_B):
            for label in LABELS:
                review[f"{candidate} {label}"] = "1"
            if mapping_by_id[review["来源"]][f"{candidate}来源"] == SYSTEM_SOURCE:
                review[f"{candidate} 意向推进 P"] = "0"
    write_csv(summary.blind_review_path, columns, reviews)

    score = score_blind_review(summary.run_dir, summary.blind_review_path)

    assert score.turns_total == 2
    assert score.human_score == 100
    assert score.system_score == 70
    assert score.score_difference == -30
    report_columns, report_rows = read_csv(score.report_path)
    assert report_columns == ("部分", "指标", "数值")
    assert report_rows[0]["部分"] == "业务结果"
    assert {
        row["指标"]: row["数值"]
        for row in report_rows
        if row["指标"] in {"系统意向推进 P通过率", "真人意向推进 P通过率"}
    } == {
        "系统意向推进 P通过率": "0.00%",
        "真人意向推进 P通过率": "100.00%",
    }
    assert any(row["部分"] == "技术工程" for row in report_rows)


class _HangingLLM:
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: str | None = None,
    ) -> LLMResponse:
        del messages, temperature, max_tokens, response_format
        await asyncio.sleep(60)
        raise AssertionError("timeout should cancel this call")


def test_production_turn_timeout_still_applies_in_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.knowledge.loader.SessionLocal", _ReadOnlyKnowledgeSession)
    settings = _settings(CHAT_REQUEST_TIMEOUT_SECONDS=0.1)
    service, _ = create_production_replay_service(_HangingLLM(), settings)

    async def run_case():
        started = asyncio.get_running_loop().time()
        result = await service.process_message("请介绍课程", session_id="timeout-test")
        return result, asyncio.get_running_loop().time() - started

    result, elapsed = asyncio.run(run_case())

    assert elapsed < 1
    assert result.state.transfer_flag is True
    assert result.agent_runs[0]["agent_name"] == "sales_graph"
