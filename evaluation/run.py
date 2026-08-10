from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# 同时支持 `python evaluation/run.py` 和 `python -m evaluation.run`。
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.conversation import ConversationState
from app.conversation.state import CustomerProfile
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.time import beijing_now
from app.graph.service import GraphSessionStore, SalesGraphService
from app.llm import DemoLLMClient, create_llm_client
from evaluation.core.csv_logger import write_csv
from evaluation.core.dataset import (
    RUN_INFO_FILENAME,
    SYSTEM_REPLY_COLUMN,
    SYSTEM_RESULTS_FILENAME,
    TECHNICAL_DETAILS_FILENAME,
    EvaluationCsvDataset,
    EvaluationDatasetError,
    EvaluationInputRow,
)
from evaluation.core.knowledge_snapshot import (
    SnapshotSafetyVectorReviewer,
    SnapshotSalesCaseRAGService,
    create_snapshot_knowledge_loader,
)


@dataclass(frozen=True)
class EvaluationRunSummary:
    run_id: str
    run_dir: Path
    turns_total: int
    turns_succeeded: int
    turns_handed_off: int
    turns_failed: int
    max_concurrency: int
    model_mode: str
    results_path: Path
    blind_review_path: Path
    blind_mapping_path: Path


@dataclass(frozen=True)
class TurnExecutionOutcome:
    status: Literal["success", "handoff", "failed"]
    error_codes: list[str]
    error_message: str


@dataclass(frozen=True)
class TurnRunResult:
    row: EvaluationInputRow
    system_reply: str
    execution_status: str
    elapsed_ms: int
    transfer_flag: bool
    transfer_reason: str
    error_codes: str
    error_message: str


def create_production_replay_service(
    llm_client: Any,
    settings: Settings,
    *,
    knowledge_loader: Any | None = None,
    sales_case_rag_service: Any | None = None,
    safety_vector_reviewer: Any | None = None,
) -> tuple[SalesGraphService, GraphSessionStore]:
    """创建无落库副作用的正式销售服务。

    图、提示词、模型与超时复用正式默认值。会话状态仅保存在本进程内；知识、
    RAG 与风控规则则只读取 evaluation/knowledge_snapshot，避免正式数据混入。
    """

    session_store = GraphSessionStore(repository=None)
    active_knowledge_loader = knowledge_loader or create_snapshot_knowledge_loader()
    service = SalesGraphService(
        llm_client,
        session_store=session_store,
        knowledge_loader=active_knowledge_loader,
        repository=None,
        sales_case_rag_service=sales_case_rag_service
        or SnapshotSalesCaseRAGService(settings=settings),
        safety_vector_reviewer=safety_vector_reviewer
        or SnapshotSafetyVectorReviewer(
            knowledge_loader=active_knowledge_loader,
            settings=settings,
        ),
        settings=settings,
        request_timeout_seconds=settings.chat_request_timeout_seconds,
    )
    return service, session_store


async def run_evaluation(
    input_csv: Path | str,
    *,
    output_root: Path | str | None = None,
    settings: Settings | None = None,
    llm_client: Any | None = None,
    run_id: str | None = None,
) -> EvaluationRunSummary:
    """并发回放 CSV 中彼此独立的对话回合，并输出系统回复和盲评表。"""

    runtime_settings = settings or get_settings()
    dataset = EvaluationCsvDataset.load(input_csv)
    active_llm_client = llm_client or create_llm_client(runtime_settings)
    model_mode = (
        "demo_model"
        if isinstance(active_llm_client, DemoLLMClient)
        else "configured_model"
    )
    # 结果目录与运行信息使用东八区时间，与业务侧展示口径一致。
    actual_run_id = run_id or beijing_now().strftime("%Y%m%dT%H%M%S%f+0800")
    root = Path(output_root or PROJECT_ROOT / "evaluation" / "results").resolve()
    run_dir = root / actual_run_id
    if run_dir.exists():
        raise FileExistsError(f"评测结果目录已存在：{run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)

    started_at = beijing_now()
    max_concurrency = runtime_settings.evaluation_max_concurrency
    semaphore = asyncio.Semaphore(max_concurrency)
    snapshot_knowledge_loader = create_snapshot_knowledge_loader()
    snapshot_rag_service = SnapshotSalesCaseRAGService(settings=runtime_settings)
    snapshot_safety_reviewer = SnapshotSafetyVectorReviewer(
        knowledge_loader=snapshot_knowledge_loader,
        settings=runtime_settings,
    )
    tasks = [
        asyncio.create_task(
            _run_single_turn(
                row=row,
                run_id=actual_run_id,
                settings=runtime_settings,
                llm_client=active_llm_client,
                semaphore=semaphore,
                knowledge_loader=snapshot_knowledge_loader,
                sales_case_rag_service=snapshot_rag_service,
                safety_vector_reviewer=snapshot_safety_reviewer,
            )
        )
        for row in dataset.rows
    ]
    turn_results = await asyncio.gather(*tasks)

    result_rows = [_result_csv_row(item, dataset) for item in turn_results]
    detail_rows = [_technical_detail_row(item) for item in turn_results]
    results_path = write_csv(
        run_dir / SYSTEM_RESULTS_FILENAME,
        dataset.result_fieldnames,
        result_rows,
    )
    write_csv(
        run_dir / TECHNICAL_DETAILS_FILENAME,
        (
            "来源",
            "运行状态",
            "耗时毫秒",
            "是否转人工",
            "转人工原因",
            "错误代码",
            "错误信息",
        ),
        detail_rows,
    )

    succeeded = sum(item.execution_status == "success" for item in turn_results)
    handed_off = sum(item.execution_status == "handoff" for item in turn_results)
    failed = sum(item.execution_status == "failed" for item in turn_results)
    write_csv(
        run_dir / RUN_INFO_FILENAME,
        ("字段", "值"),
        [
            {"字段": "运行标识", "值": actual_run_id},
            {"字段": "输入文件", "值": str(dataset.source_path)},
            {"字段": "输入文件SHA256", "值": dataset.sha256},
            {"字段": "模型模式", "值": model_mode},
            {"字段": "模型供应商配置", "值": runtime_settings.llm_provider},
            {"字段": "评测并发数", "值": max_concurrency},
            {"字段": "单轮超时秒数", "值": runtime_settings.chat_request_timeout_seconds},
            {"字段": "总轮次", "值": len(turn_results)},
            {"字段": "正常回复", "值": succeeded},
            {"字段": "转人工", "值": handed_off},
            {"字段": "失败", "值": failed},
            {"字段": "开始时间(东八区)", "值": started_at.isoformat()},
            {"字段": "结束时间(东八区)", "值": beijing_now().isoformat()},
        ],
    )

    # 评测运行完成即生成盲评表；映射文件仅供汇总脚本使用，不能发给评审人。
    from evaluation.core.scoring import create_blind_review_package

    blind_review_path, blind_mapping_path = create_blind_review_package(run_dir)
    return EvaluationRunSummary(
        run_id=actual_run_id,
        run_dir=run_dir,
        turns_total=len(turn_results),
        turns_succeeded=succeeded,
        turns_handed_off=handed_off,
        turns_failed=failed,
        max_concurrency=max_concurrency,
        model_mode=model_mode,
        results_path=results_path,
        blind_review_path=blind_review_path,
        blind_mapping_path=blind_mapping_path,
    )


def _parse_memory_summary(memory_summary: str) -> tuple[str, CustomerProfile]:
    """解析评测 CSV『上文记忆』JSON，还原上文摘要与客户画像。

    评测数据中该列是 {"history_summary": "...", "customer_profile": {...}} 结构的
    JSON。正式环境从数据库恢复画像，评测环境应尽量还原同一状态，否则意图识别等
    环节看不到客户的已报名状态。解析失败时回退为现状（整段文本 + 空画像）。
    """
    if not memory_summary:
        return "", CustomerProfile()
    try:
        parsed = json.loads(memory_summary)
    except (ValueError, TypeError):
        return memory_summary, CustomerProfile()
    if not isinstance(parsed, dict):
        return memory_summary, CustomerProfile()
    history = parsed.get("history_summary")
    result_history = (
        history if isinstance(history, str) and history.strip() else memory_summary
    )
    profile_data = parsed.get("customer_profile")
    if isinstance(profile_data, dict):
        try:
            return result_history, CustomerProfile.model_validate(profile_data)
        except Exception:
            return result_history, CustomerProfile()
    return result_history, CustomerProfile()


async def _run_single_turn(
    *,
    row: EvaluationInputRow,
    run_id: str,
    settings: Settings,
    llm_client: Any,
    semaphore: asyncio.Semaphore,
    knowledge_loader: Any,
    sales_case_rag_service: Any,
    safety_vector_reviewer: Any,
) -> TurnRunResult:
    """每行独立模拟一个正式新会话，且只把 CSV 的记忆列注入为上文记忆。"""

    async with semaphore:
        started = time.perf_counter()
        service, session_store = create_production_replay_service(
            llm_client,
            settings,
            knowledge_loader=knowledge_loader,
            sales_case_rag_service=sales_case_rag_service,
            safety_vector_reviewer=safety_vector_reviewer,
        )
        session_id = _session_id(run_id, row.turn_id)
        history_summary, customer_profile = _parse_memory_summary(row.memory_summary)
        session_store.save(
            ConversationState(
                session_id=session_id,
                customer_id=f"evaluation-{session_id[-16:]}",
                customer_profile=customer_profile,
                history_summary=history_summary,
            )
        )
        try:
            result = await service.process_message(
                row.user_message,
                session_id=session_id,
                client_message_id=f"evaluation:{row.turn_id}",
            )
            outcome = _classify_execution_outcome(result)
            return TurnRunResult(
                row=row,
                system_reply=_reply_cell(result.reply),
                execution_status=outcome.status,
                elapsed_ms=max(1, int((time.perf_counter() - started) * 1000)),
                transfer_flag=bool(result.state.transfer_flag),
                transfer_reason=str(result.state.transfer_reason or ""),
                error_codes=";".join(outcome.error_codes),
                error_message=outcome.error_message,
            )
        except Exception as exc:
            return TurnRunResult(
                row=row,
                system_reply="",
                execution_status="failed",
                elapsed_ms=max(1, int((time.perf_counter() - started) * 1000)),
                transfer_flag=False,
                transfer_reason="",
                error_codes="exception",
                error_message=f"{type(exc).__name__}: {str(exc)[:500]}",
            )


def _result_csv_row(
    result: TurnRunResult,
    dataset: EvaluationCsvDataset,
) -> dict[str, str]:
    values = dict(result.row.values)
    values[SYSTEM_REPLY_COLUMN] = result.system_reply
    # 字段顺序由 dataset.result_fieldnames 控制；这里保留原 CSV 的所有单元格值。
    return {name: values.get(name, "") for name in dataset.result_fieldnames}


def _technical_detail_row(result: TurnRunResult) -> dict[str, Any]:
    return {
        "来源": result.row.turn_id,
        "运行状态": result.execution_status,
        "耗时毫秒": result.elapsed_ms,
        "是否转人工": "是" if result.transfer_flag else "否",
        "转人工原因": result.transfer_reason,
        "错误代码": result.error_codes,
        "错误信息": result.error_message,
    }


def _classify_execution_outcome(result: Any) -> TurnExecutionOutcome:
    """将正常转人工与工程失败分开记录，避免空回复被错误算作成功。"""

    error_codes: list[str] = []
    error_messages: list[str] = []
    for run in result.agent_runs or []:
        if not isinstance(run, dict) or run.get("success") is not False:
            continue
        agent_name = str(run.get("agent_name") or "unknown_agent")
        error_codes.append(f"agent_failed:{agent_name}")
        detail = str(run.get("error_message") or "agent reported failure").strip()
        error_messages.append(f"{agent_name}: {detail[:240]}")

    reply = str(result.reply or "").strip()
    transferred = bool(result.state.transfer_flag)
    if not reply and not transferred:
        error_codes.append("empty_reply")
        error_messages.append("图执行完成但没有客户可见回复，也没有有效转人工标记。")
    if error_codes:
        return TurnExecutionOutcome("failed", error_codes, "；".join(error_messages))
    if transferred:
        return TurnExecutionOutcome("handoff", [], "")
    return TurnExecutionOutcome("success", [], "")


def _reply_cell(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _session_id(run_id: str, turn_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{turn_id}".encode("utf-8")).hexdigest()
    return f"evaluation-{digest[:24]}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="并发运行 Sales Agent 正式链路 CSV 评测")
    parser.add_argument("--input-csv", type=Path, required=True, help="四列原始评测对话 CSV")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "results",
        help="本地结果目录根路径",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="使用本地确定性演示模型，不调用外部模型 API",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = asyncio.run(
            run_evaluation(
                args.input_csv,
                output_root=args.output_root,
                settings=get_settings(),
                llm_client=DemoLLMClient(delay_ms=0) if args.demo else None,
            )
        )
    except (EvaluationDatasetError, FileExistsError) as exc:
        print(f"评测未运行：{exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "run_id": summary.run_id,
                "run_dir": str(summary.run_dir),
                "turns_total": summary.turns_total,
                "turns_succeeded": summary.turns_succeeded,
                "turns_handed_off": summary.turns_handed_off,
                "turns_failed": summary.turns_failed,
                "max_concurrency": summary.max_concurrency,
                "model_mode": summary.model_mode,
                "system_results": str(summary.results_path),
                "blind_review": str(summary.blind_review_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if summary.turns_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
