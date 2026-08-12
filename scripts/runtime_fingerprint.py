"""计算 MCP Docker 构建输入的稳定指纹。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_INPUTS = (
    ROOT / ".dockerignore",
    ROOT / "requirements.txt",
    ROOT / "deployment" / "Dockerfile.mcp",
    ROOT / "app",
    ROOT / "data",
    ROOT / "prompts",
    ROOT / "evaluation",
    ROOT / "sales_agent_teams",
    ROOT / "mcp_servers",
)
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "private_datasets",
    "results",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def iter_build_files() -> list[Path]:
    files: list[Path] = []
    for path in BUILD_INPUTS:
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            relative = candidate.relative_to(ROOT)
            if (
                candidate.is_file()
                and not EXCLUDED_PARTS.intersection(relative.parts)
                and candidate.suffix.lower() not in EXCLUDED_SUFFIXES
            ):
                files.append(candidate)
    return sorted(set(files), key=lambda item: item.relative_to(ROOT).as_posix())


def build_fingerprint() -> str:
    digest = sha256()
    for file in iter_build_files():
        relative = file.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


if __name__ == "__main__":
    print(build_fingerprint())
