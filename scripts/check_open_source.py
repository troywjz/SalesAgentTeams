"""发布前检查 Git 追踪内容没有本地环境、私有数据和明显密钥。"""

from __future__ import annotations

import subprocess
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = ("private_datasets/", ".venv/", "__pycache__/", "evaluation/results/")
SECRET_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*(?:API_KEY|SECRET_KEY|PASSWORD|TOKEN))[ \t]*=[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
PLACEHOLDER_VALUES = {"", "test-key", "admin123", "123456", "change-me", "changeme"}
LOCAL_PATH_PATTERN = re.compile(
    r"(?:C:\\Users\\|D:\\code\\|D:/code/|wsl\.localhost)",
    re.IGNORECASE,
)
ARCHIVE_SUFFIXES = {".zip", ".pptx"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    files = tracked_files()
    violations: list[str] = []
    for name in files:
        normalized = name.replace("\\", "/").lower()
        if normalized == ".env" or (
            any(part in normalized for part in FORBIDDEN_PARTS)
            and not normalized.endswith("/.gitkeep")
        ):
            violations.append(f"禁止追踪路径: {name}")
            continue
        path = ROOT / name
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            try:
                with ZipFile(path) as archive:
                    for member in archive.namelist():
                        payload = archive.read(member)
                        if LOCAL_PATH_PATTERN.search(payload.decode("utf-8", errors="ignore")):
                            violations.append(f"压缩工件含本机路径: {name}!{member}")
                            break
            except (BadZipFile, OSError):
                violations.append(f"压缩工件不可读取: {name}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # 检查器本身需要包含被禁止模式的正则文本，不将规则定义误报为泄漏。
        if normalized != "scripts/check_open_source.py" and LOCAL_PATH_PATTERN.search(text):
            violations.append(f"含本机绝对路径: {name}")
        for match in SECRET_ASSIGNMENT.finditer(text):
            value = match.group(2).strip().rstrip(",").strip().strip("'\"").lower()
            if value in PLACEHOLDER_VALUES or value.startswith("${"):
                continue
            if "change-before-public" in value or value.startswith("your-"):
                continue
            violations.append(f"疑似敏感内容: {name}")
            break
    if violations:
        raise SystemExit("\n".join(violations))
    print(f"开源审计通过：检查 {len(files)} 个追踪文件。")


if __name__ == "__main__":
    main()
