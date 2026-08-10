import pytest

from app.utils.json_tools import extract_json_object


def test_extract_json_object_preserves_apostrophes_inside_strings() -> None:
    raw = (
        '{'
        '"intent_category":"course_inquiry",'
        '"reason":"客户说\'了解一下\'，属于开场咨询"'
        '}'
    )

    result = extract_json_object(raw)

    assert result["reason"] == "客户说'了解一下'，属于开场咨询"


def test_extract_json_object_handles_fenced_json_with_trailing_comma() -> None:
    raw = """```json
{
  "thinking": "客户回答'高中'，需要继续确认需求",
  "final_reply": "明白了，您是高中毕业。",
}
```"""

    result = extract_json_object(raw)

    assert result["thinking"] == "客户回答'高中'，需要继续确认需求"
    assert result["final_reply"] == "明白了，您是高中毕业。"


def test_extract_json_object_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="Expected a JSON object"):
        extract_json_object('["not", "object"]')
