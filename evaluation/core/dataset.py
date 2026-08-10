from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path


# 正式评测输入的前四列固定；后续附加列允许保留，但不会进入模型上下文。
INPUT_COLUMNS = (
    "来源",
    "用户消息",
    "销售回复",
    "上文记忆",
)
SYSTEM_REPLY_COLUMN = "系统销售回复"
SYSTEM_RESULTS_FILENAME = "系统回复结果.csv"
TECHNICAL_DETAILS_FILENAME = "技术运行明细.csv"
RUN_INFO_FILENAME = "运行信息.csv"
BLIND_REVIEW_FILENAME = "盲评表.csv"
BLIND_MAPPING_FILENAME = "盲评映射.csv"


class EvaluationDatasetError(ValueError):
    """评测 CSV 缺失、编码错误或不符合约定的列结构。"""


@dataclass(frozen=True)
class EvaluationInputRow:
    row_number: int
    turn_id: str
    user_message: str
    human_sales_reply: str
    memory_summary: str
    values: dict[str, str]


@dataclass(frozen=True)
class EvaluationCsvDataset:
    source_path: Path
    fieldnames: tuple[str, ...]
    rows: tuple[EvaluationInputRow, ...]
    sha256: str

    @classmethod
    def load(cls, path: Path | str) -> "EvaluationCsvDataset":
        source_path = Path(path).resolve()
        if not source_path.is_file():
            raise EvaluationDatasetError(f"评测对话 CSV 不存在：{source_path}")
        try:
            file = io.StringIO(
                source_path.read_bytes().decode("utf-8-sig"),
                newline="",
            )
        except UnicodeDecodeError as exc:
            raise EvaluationDatasetError("评测对话 CSV 必须使用 UTF-8 编码。") from exc

        with file:
            reader = csv.DictReader(file)
            fieldnames = tuple(str(name or "").strip() for name in (reader.fieldnames or []))
            if fieldnames[: len(INPUT_COLUMNS)] != INPUT_COLUMNS:
                expected = "、".join(INPUT_COLUMNS)
                actual = "、".join(fieldnames[: len(INPUT_COLUMNS)]) or "无"
                raise EvaluationDatasetError(
                    f"评测 CSV 前四列必须依次为：{expected}；当前为：{actual}。"
                )
            if len(set(fieldnames)) != len(fieldnames) or any(not name for name in fieldnames):
                raise EvaluationDatasetError("评测 CSV 的列名必须非空且不能重复。")
            if SYSTEM_REPLY_COLUMN in fieldnames:
                raise EvaluationDatasetError(
                    f"输入 CSV 不应包含“{SYSTEM_REPLY_COLUMN}”；请传入原始四列评测表。"
                )

            rows: list[EvaluationInputRow] = []
            seen_turn_ids: set[str] = set()
            for row_number, raw in enumerate(reader, start=2):
                values = {
                    name: "" if raw.get(name) is None else str(raw.get(name))
                    for name in fieldnames
                }
                if not any(value.strip() for value in values.values()):
                    continue
                turn_id = values[INPUT_COLUMNS[0]].strip()
                user_message = values[INPUT_COLUMNS[1]].strip()
                human_sales_reply = values[INPUT_COLUMNS[2]].strip()
                memory_summary = values[INPUT_COLUMNS[3]].strip()
                if not turn_id or not user_message:
                    raise EvaluationDatasetError(
                        f"评测 CSV 第 {row_number} 行必须填写来源和用户消息。"
                    )
                if turn_id in seen_turn_ids:
                    raise EvaluationDatasetError(f"评测 CSV 存在重复来源：{turn_id}")
                seen_turn_ids.add(turn_id)
                rows.append(
                    EvaluationInputRow(
                        row_number=row_number,
                        turn_id=turn_id,
                        user_message=user_message,
                        human_sales_reply=human_sales_reply,
                        memory_summary=memory_summary,
                        values=values,
                    )
                )

        if not rows:
            raise EvaluationDatasetError("评测 CSV 没有可运行的对话回合。")
        return cls(
            source_path=source_path,
            fieldnames=fieldnames,
            rows=tuple(rows),
            sha256=_sha256(source_path),
        )

    @property
    def result_fieldnames(self) -> tuple[str, ...]:
        # 系统回复固定插入为第五列；原 CSV 的其余列仍按原顺序保留。
        return (
            *self.fieldnames[: len(INPUT_COLUMNS)],
            SYSTEM_REPLY_COLUMN,
            *self.fieldnames[len(INPUT_COLUMNS) :],
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
