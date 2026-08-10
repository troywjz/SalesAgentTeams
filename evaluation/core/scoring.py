from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.core.csv_logger import read_csv, write_csv
from evaluation.core.dataset import (
    BLIND_MAPPING_FILENAME,
    BLIND_REVIEW_FILENAME,
    INPUT_COLUMNS,
    SYSTEM_REPLY_COLUMN,
    SYSTEM_RESULTS_FILENAME,
    TECHNICAL_DETAILS_FILENAME,
)


CANDIDATE_A = "候选甲"
CANDIDATE_B = "候选乙"
HUMAN_SOURCE = "真人销售"
SYSTEM_SOURCE = "系统销售"
LABELS = (
    "信息准确 A",
    "不违规 C",
    "解决问题 R",
    "意向推进 P",
    "用户反馈 F",
)
# 回合标识列统一沿用输入数据集的“来源”列名，输入输出表格保持同名字段。
TURN_ID_COLUMN = "来源"
BLIND_REVIEW_COLUMNS = (
    TURN_ID_COLUMN,
    "用户消息",
    "上文记忆",
    f"{CANDIDATE_A}回复",
    f"{CANDIDATE_B}回复",
    *[f"{CANDIDATE_A} {label}" for label in LABELS],
    *[f"{CANDIDATE_B} {label}" for label in LABELS],
    "评审人",
    "评审备注",
)
BLIND_MAPPING_COLUMNS = (
    TURN_ID_COLUMN,
    f"{CANDIDATE_A}来源",
    f"{CANDIDATE_B}来源",
)
SCORE_DETAIL_COLUMNS = (
    TURN_ID_COLUMN,
    "回复来源",
    *LABELS,
    "基础分",
    "最终分",
    "评审人",
    "评审备注",
)


class EvaluationScoringError(ValueError):
    """盲评表、映射表或评分汇总不符合约定。"""


@dataclass(frozen=True)
class ComparisonSummary:
    run_dir: Path
    review_file: Path
    score_detail_path: Path
    report_path: Path
    turns_total: int
    human_score: float
    system_score: float
    score_difference: float
    technical_failed_turns: int


def create_blind_review_package(
    run_dir: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """生成发给评审人的盲评表与仅供程序保留的来源映射表。"""

    root = Path(run_dir).resolve()
    result_columns, result_rows = read_csv(root / SYSTEM_RESULTS_FILENAME)
    _validate_result_columns(result_columns)
    technical_status = _technical_status_by_turn(root)
    review_path = root / BLIND_REVIEW_FILENAME
    mapping_path = root / BLIND_MAPPING_FILENAME
    if not overwrite and (review_path.exists() or mapping_path.exists()):
        raise EvaluationScoringError("盲评表或来源映射已存在，拒绝覆盖。")

    review_rows: list[dict[str, str]] = []
    mapping_rows: list[dict[str, str]] = []
    seen_turn_ids: set[str] = set()
    for result in result_rows:
        turn_id = _required(result, "来源")
        if turn_id in seen_turn_ids:
            raise EvaluationScoringError(f"系统回复结果存在重复来源：{turn_id}")
        seen_turn_ids.add(turn_id)
        human_reply = result.get("销售回复", "")
        system_reply = result.get(SYSTEM_REPLY_COLUMN, "")
        first_source, second_source = _candidate_sources(turn_id)
        replies = {
            HUMAN_SOURCE: human_reply,
            SYSTEM_SOURCE: system_reply,
        }
        review_rows.append(
            {
                TURN_ID_COLUMN: turn_id,
                "用户消息": result.get("用户消息", ""),
                "上文记忆": result.get("上文记忆", ""),
                f"{CANDIDATE_A}回复": replies[first_source],
                f"{CANDIDATE_B}回复": replies[second_source],
                **{f"{candidate} {label}": "" for candidate in (CANDIDATE_A, CANDIDATE_B) for label in LABELS},
                "评审人": "",
                "评审备注": "",
            }
        )
        mapping_rows.append(
            {
                TURN_ID_COLUMN: turn_id,
                f"{CANDIDATE_A}来源": first_source,
                f"{CANDIDATE_B}来源": second_source,
            }
        )

    if not review_rows:
        raise EvaluationScoringError("系统回复结果没有可盲评的对话回合。")
    _ensure_same_turn_ids(technical_status, seen_turn_ids, "技术运行明细")
    write_csv(review_path, BLIND_REVIEW_COLUMNS, review_rows)
    write_csv(mapping_path, BLIND_MAPPING_COLUMNS, mapping_rows)
    return review_path, mapping_path


def score_blind_review(
    run_dir: Path | str,
    review_file: Path | str,
    *,
    mapping_file: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> ComparisonSummary:
    """将盲评结果映射回真人/系统来源，并按既定五维公式分别计分。"""

    root = Path(run_dir).resolve()
    result_columns, result_rows = read_csv(root / SYSTEM_RESULTS_FILENAME)
    _validate_result_columns(result_columns)
    review_path = Path(review_file).resolve()
    review_columns, review_rows = read_csv(review_path)
    _require_columns(review_columns, BLIND_REVIEW_COLUMNS, "盲评表")
    map_path = Path(mapping_file or root / BLIND_MAPPING_FILENAME).resolve()
    mapping_columns, mapping_rows = read_csv(map_path)
    _require_columns(mapping_columns, BLIND_MAPPING_COLUMNS, "盲评映射")

    results_by_id = _rows_by_turn_id(result_rows, "系统回复结果", key_column="来源")
    reviews_by_id = _rows_by_turn_id(review_rows, "盲评表", key_column=TURN_ID_COLUMN)
    mappings_by_id = _rows_by_turn_id(mapping_rows, "盲评映射", key_column=TURN_ID_COLUMN)
    _ensure_same_turn_ids(results_by_id, set(reviews_by_id), "盲评表")
    _ensure_same_turn_ids(results_by_id, set(mappings_by_id), "盲评映射")
    technical_status = _technical_status_by_turn(root)
    _ensure_same_turn_ids(technical_status, set(results_by_id), "技术运行明细")

    details: list[dict[str, Any]] = []
    scores: dict[str, list[float]] = {HUMAN_SOURCE: [], SYSTEM_SOURCE: []}
    label_values: dict[str, dict[str, list[int]]] = {
        HUMAN_SOURCE: {label: [] for label in LABELS},
        SYSTEM_SOURCE: {label: [] for label in LABELS},
    }
    technical_failed = 0
    for result in result_rows:
        turn_id = _required(result, "来源")
        review = reviews_by_id[turn_id]
        mapping = mappings_by_id[turn_id]
        status = technical_status[turn_id]
        if status == "failed":
            technical_failed += 1
        reviewer = review.get("评审人", "").strip()
        note = review.get("评审备注", "").strip()
        for candidate in (CANDIDATE_A, CANDIDATE_B):
            source = mapping.get(f"{candidate}来源", "")
            if source not in {HUMAN_SOURCE, SYSTEM_SOURCE}:
                raise EvaluationScoringError(
                    f"盲评映射中 {turn_id} 的 {candidate}来源无效。"
                )
            if source == SYSTEM_SOURCE and status == "failed":
                labels = _zero_labels()
            else:
                labels = _parse_labels(review, candidate, turn_id)
            base_score = 30 * labels["解决问题 R"] + 30 * labels["意向推进 P"] + 40 * labels["用户反馈 F"]
            final_score = base_score * labels["信息准确 A"] * labels["不违规 C"]
            scores[source].append(float(final_score))
            for label, value in labels.items():
                label_values[source][label].append(value)
            details.append(
                {
                    TURN_ID_COLUMN: turn_id,
                    "回复来源": source,
                    **labels,
                    "基础分": base_score,
                    "最终分": final_score,
                    "评审人": reviewer,
                    "评审备注": note,
                }
            )

    turns_total = len(result_rows)
    if not turns_total:
        raise EvaluationScoringError("系统回复结果没有可评分的对话回合。")
    if len(scores[HUMAN_SOURCE]) != turns_total or len(scores[SYSTEM_SOURCE]) != turns_total:
        raise EvaluationScoringError("盲评映射未能为每个对话回合配对真人与系统回复。")
    human_score = sum(scores[HUMAN_SOURCE]) / turns_total
    system_score = sum(scores[SYSTEM_SOURCE]) / turns_total
    difference = system_score - human_score
    label_rates = {
        source: {
            label: sum(values) / turns_total
            for label, values in labels_by_source.items()
        }
        for source, labels_by_source in label_values.items()
    }

    destination = Path(output_dir or root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    score_detail_path = write_csv(destination / "评分明细.csv", SCORE_DETAIL_COLUMNS, details)
    report_path = write_csv(
        destination / "评估报告.csv",
        ("部分", "指标", "数值"),
        _report_rows(
            human_score=human_score,
            system_score=system_score,
            difference=difference,
            turns_total=turns_total,
            technical_status=technical_status,
            label_rates=label_rates,
        ),
    )
    return ComparisonSummary(
        run_dir=root,
        review_file=review_path,
        score_detail_path=score_detail_path,
        report_path=report_path,
        turns_total=turns_total,
        human_score=human_score,
        system_score=system_score,
        score_difference=difference,
        technical_failed_turns=technical_failed,
    )


def _candidate_sources(turn_id: str) -> tuple[str, str]:
    # 每个回合独立且稳定地打乱顺序，映射文件保存真实来源，评审表本身不暴露来源。
    value = int(hashlib.sha256(turn_id.encode("utf-8")).hexdigest()[-1], 16)
    return (HUMAN_SOURCE, SYSTEM_SOURCE) if value % 2 == 0 else (SYSTEM_SOURCE, HUMAN_SOURCE)


def _technical_status_by_turn(root: Path) -> dict[str, str]:
    columns, rows = read_csv(root / TECHNICAL_DETAILS_FILENAME)
    _require_columns(columns, (TURN_ID_COLUMN, "运行状态"), "技术运行明细")
    return {
        turn_id: row.get("运行状态", "failed") or "failed"
        for turn_id, row in _rows_by_turn_id(rows, "技术运行明细", key_column=TURN_ID_COLUMN).items()
    }


def _report_rows(
    *,
    human_score: float,
    system_score: float,
    difference: float,
    turns_total: int,
    technical_status: dict[str, str],
    label_rates: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    # 报告固定先业务、后工程；逐轮耗时保留在技术运行明细中。
    status_counts = {
        status: sum(value == status for value in technical_status.values())
        for status in ("success", "handoff", "failed")
    }
    conclusion = (
        "系统与真人销售平均分相同"
        if difference == 0
        else (
            f"系统平均分高于真人销售 {difference:.2f} 分"
            if difference > 0
            else f"系统平均分低于真人销售 {abs(difference):.2f} 分"
        )
    )
    rows: list[dict[str, Any]] = [
        {"部分": "业务结果", "指标": "参评回合数", "数值": turns_total},
        {"部分": "业务结果", "指标": "系统销售平均分", "数值": f"{system_score:.2f}"},
        {"部分": "业务结果", "指标": "真人销售平均分", "数值": f"{human_score:.2f}"},
        {"部分": "业务结果", "指标": "系统减真人分差", "数值": f"{difference:.2f}"},
    ]
    for label in LABELS:
        rows.extend(
            (
                {
                    "部分": "业务结果",
                    "指标": f"系统{label}通过率",
                    "数值": f"{label_rates[SYSTEM_SOURCE][label]:.2%}",
                },
                {
                    "部分": "业务结果",
                    "指标": f"真人{label}通过率",
                    "数值": f"{label_rates[HUMAN_SOURCE][label]:.2%}",
                },
            )
        )
    rows.extend(
        (
            {"部分": "业务结果", "指标": "结论", "数值": conclusion},
            {"部分": "技术工程", "指标": "正常回复", "数值": status_counts["success"]},
            {"部分": "技术工程", "指标": "转人工", "数值": status_counts["handoff"]},
            {"部分": "技术工程", "指标": "失败", "数值": status_counts["failed"]},
        )
    )
    return rows


def _parse_labels(row: dict[str, str], candidate: str, turn_id: str) -> dict[str, int]:
    labels: dict[str, int] = {}
    for label in LABELS:
        value = row.get(f"{candidate} {label}", "").strip()
        if value not in {"0", "1"}:
            raise EvaluationScoringError(
                f"盲评表 {turn_id} 的“{candidate} {label}”必须填写 0 或 1。"
            )
        labels[label] = int(value)
    return labels


def _zero_labels() -> dict[str, int]:
    return {label: 0 for label in LABELS}


def _validate_result_columns(columns: tuple[str, ...]) -> None:
    _require_columns(
        columns,
        (*INPUT_COLUMNS, SYSTEM_REPLY_COLUMN),
        "系统回复结果",
    )


def _require_columns(
    actual: tuple[str, ...],
    expected: tuple[str, ...],
    source_name: str,
) -> None:
    missing = [column for column in expected if column not in actual]
    if missing:
        raise EvaluationScoringError(
            f"{source_name} 缺少列：" + "、".join(missing)
        )


def _rows_by_turn_id(
    rows: list[dict[str, str]],
    source_name: str,
    *,
    key_column: str,
) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for row in rows:
        turn_id = _required(row, key_column)
        if turn_id in values:
            raise EvaluationScoringError(f"{source_name} 存在重复回合标识：{turn_id}")
        values[turn_id] = row
    return values


def _ensure_same_turn_ids(
    left: dict[str, Any] | set[str],
    right: dict[str, Any] | set[str],
    source_name: str,
) -> None:
    left_ids = set(left)
    right_ids = set(right)
    if left_ids == right_ids:
        return
    missing = sorted(left_ids - right_ids)
    unexpected = sorted(right_ids - left_ids)
    details: list[str] = []
    if missing:
        details.append(f"缺少 {len(missing)} 个回合")
    if unexpected:
        details.append(f"多出 {len(unexpected)} 个回合")
    raise EvaluationScoringError(f"{source_name} 与系统回复结果不一致：" + "；".join(details))


def _required(row: dict[str, str], column: str) -> str:
    value = row.get(column, "").strip()
    if not value:
        raise EvaluationScoringError(f"CSV 缺少非空“{column}”。")
    return value
