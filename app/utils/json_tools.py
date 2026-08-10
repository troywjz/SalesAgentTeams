import json
import re
from ast import literal_eval
from typing import Any


def _strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else cleaned


def _remove_trailing_commas(text: str) -> str:
    """修复常见尾逗号错误: ,} -> } 和 ,] -> ]。"""
    return re.sub(r",(\s*[}\]])", r"\1", text).strip()


def _extract_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response.")

    depth = 0
    end = -1
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        end = text.rfind("}")
        if end == -1 or end <= start:
            raise ValueError("No complete JSON object found in response.")

    return text[start : end + 1]


def _literal_eval_dict(candidate: str) -> dict[str, Any] | None:
    try:
        value = literal_eval(candidate)
    except (SyntaxError, ValueError):
        return None

    return value if isinstance(value, dict) else None


def extract_json_object(text: str) -> dict[str, Any]:
    """从 LLM 输出中提取 JSON 对象。

    解析顺序必须先尝试原样 JSON。模型经常在中文字符串里使用
    单引号（如 客户说'高中'），不能全局替换单引号，否则会破坏合法 JSON。
    """
    cleaned = _strip_markdown_fence(text)
    candidates = [cleaned]
    try:
        extracted = _extract_balanced_object(cleaned)
    except ValueError:
        extracted = ""
    if extracted and extracted != cleaned:
        candidates.append(extracted)

    repaired_candidates: list[str] = []
    for candidate in candidates:
        repaired = _remove_trailing_commas(candidate)
        repaired_candidates.append(candidate)
        if repaired != candidate:
            repaired_candidates.append(repaired)

    last_error: json.JSONDecodeError | None = None
    for candidate in repaired_candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(value, dict):
            return value
        raise ValueError("Expected a JSON object.")

    # 兼容少量模型输出 Python 风格字典的情况，但不做全局单引号替换。
    for candidate in repaired_candidates:
        value = _literal_eval_dict(candidate)
        if value is not None:
            return value

    if last_error is not None:
        raise last_error
    raise ValueError("No JSON object found in response.")
