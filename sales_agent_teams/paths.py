"""限制 MCP 文件工具只能访问公开项目目录。"""

from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = PROJECT_ROOT / "evaluation"
PUBLIC_INPUT_ROOT = EVALUATION_ROOT / "datasets"
RESULT_ROOT = EVALUATION_ROOT / "results"


def resolve_public_path(value: str | Path, *, allow_missing: bool = False) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    allowed_roots = (EVALUATION_ROOT.resolve(),)
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError("路径必须位于项目 evaluation 目录内。")
    if resolved.name == ".env" or any(part.startswith(".") and part not in {".", ".."} for part in resolved.parts):
        raise ValueError("禁止访问隐藏配置或本地环境文件。")
    if not allow_missing and not resolved.exists():
        raise FileNotFoundError(f"文件或目录不存在: {resolved}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
