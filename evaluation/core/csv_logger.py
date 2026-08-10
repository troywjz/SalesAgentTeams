from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable


def write_csv(
    path: Path | str,
    fieldnames: Iterable[str],
    rows: Iterable[dict[str, Any]],
) -> Path:
    """以 UTF-8 BOM 写出 CSV，便于 Windows Excel 正确显示中文与换行。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(fieldnames)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    return destination


def read_csv(path: Path | str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = tuple(str(name or "").strip() for name in (reader.fieldnames or []))
        rows = [
            {name: "" if row.get(name) is None else str(row.get(name)) for name in fieldnames}
            for row in reader
            if row is not None
        ]
    return fieldnames, rows
