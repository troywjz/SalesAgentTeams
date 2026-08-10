"""发布前检查 Git 追踪内容没有本地环境、私有数据和明显密钥。"""

from __future__ import annotations

import subprocess
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = ("private_datasets/", ".venv/", "__pycache__/", "evaluation/results/")
SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*(?:API_KEY|SECRET_KEY|PASSWORD|TOKEN))\s*=\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PLACEHOLDER_VALUES = {"", "test-key", "admin123", "123456", "change-me", "changeme"}


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
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # `.env.example` 只允许放脱敏占位值；它本身是公开配置模板，不能按实际
        # 密钥文件的规则把 `ADMIN_PASSWORD=admin123` 这类演示默认值误报为泄漏。
        if normalized == ".env.example":
            continue
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
