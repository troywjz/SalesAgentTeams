"""将公开 Worker 配置和 SKILL.md 打包成 AgentTeams 可导入的 zip。"""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
WORKERS_ROOT = ROOT / "workers"
OUTPUT_ROOT = ROOT / "worker-packages"
COMMON_ROOT = WORKERS_ROOT / "common"


def build() -> list[Path]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for worker_dir in sorted(
        path
        for path in WORKERS_ROOT.iterdir()
        if path.is_dir() and path.name not in {"common", "evaluation_operator"}
    ):
        destination = OUTPUT_ROOT / f"{worker_dir.name}.zip"
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
            for file in sorted(path for path in worker_dir.rglob("*") if path.is_file()):
                archive.write(file, file.relative_to(worker_dir).as_posix())
            for file in sorted(path for path in COMMON_ROOT.rglob("*") if path.is_file()):
                archive.write(file, file.relative_to(COMMON_ROOT).as_posix())
        outputs.append(destination)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    for output in build():
        print(output)


if __name__ == "__main__":
    main()
