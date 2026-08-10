"""已报名客户日常跟进不误转人工的确定性兜底规则测试。"""

import pytest

from app.graph.routing_rules import (
    customer_is_enrolled,
    has_new_purchase_signal,
    intent_handover_reasons,
    intent_should_handover,
)

HIGH_INTENT = {"intent_category": "high_intent", "purchase_intent": "high", "emotion": "neutral"}


@pytest.mark.parametrize(
    ("purchase_intent", "expected"),
    [
        ("已报名（四证班，已交100元定金，进VIP学习打卡群）", True),
        ("已报名缴费，课程已开通（300元内部价）", True),
        ("已购买高级办公技能认证课程", True),
        ("已进班学习", True),
        ("已交费报名办公技能初级，学习进行中", True),
        ("确定报400元班级，准备进班", False),
        ("考虑中，未决定", False),
        ("报名推进中", False),
        ("", False),
    ],
)
def test_customer_is_enrolled_matches_only_confirmed_states(
    purchase_intent: str, expected: bool
) -> None:
    assert customer_is_enrolled({"purchase_intent": purchase_intent}) is expected
    assert customer_is_enrolled(None) is False
    assert customer_is_enrolled({}) is False


def test_has_new_purchase_signal_detects_buying_language() -> None:
    assert has_new_purchase_signal("再报一科，付款链接发我") is True
    assert has_new_purchase_signal("报名链接发我") is True
    assert has_new_purchase_signal("转介绍给同事") is True
    assert has_new_purchase_signal("回头补可以补？晚上没时间") is False
    assert has_new_purchase_signal("还没听 这两天有事") is False
    assert has_new_purchase_signal("其他资料没发？") is False


def test_enrolled_customer_follow_up_does_not_handover() -> None:
    profile = {"purchase_intent": "已报名（四证班，已交100元定金）"}
    assert intent_handover_reasons(
        HIGH_INTENT, message="回头补可以补？晚上没时间", profile=profile
    ) == []
    assert intent_should_handover(
        HIGH_INTENT, message="还没听，这两天有事", profile=profile
    ) is False


def test_enrolled_customer_with_new_purchase_signal_still_handovers() -> None:
    profile = {"purchase_intent": "已报名（四证班，已交100元定金）"}
    assert intent_handover_reasons(
        HIGH_INTENT, message="再报一科，付款链接发我", profile=profile
    ) == ["意图类别=high_intent", "购买意向=high"]
    assert intent_should_handover(
        HIGH_INTENT, message="报名链接发我", profile=profile
    ) is True


def test_new_customer_high_intent_still_handovers() -> None:
    assert intent_should_handover(HIGH_INTENT, message="我想报名", profile={}) is True
    assert intent_should_handover(HIGH_INTENT, message="想报名", profile=None) is True


def test_enrolled_customer_impatient_still_handovers() -> None:
    intent = {"intent_category": "course_inquiry", "purchase_intent": "low", "emotion": "impatient"}
    profile = {"purchase_intent": "已报名缴费"}
    assert intent_handover_reasons(intent, message="别废话", profile=profile) == [
        "情绪=impatient"
    ]
    assert intent_should_handover(intent, message="别废话", profile=profile) is True


def test_enrolled_customer_should_transfer_flag_still_handovers() -> None:
    intent = {"should_transfer": True, "intent_category": "course_inquiry", "purchase_intent": "low"}
    profile = {"purchase_intent": "已报名缴费"}
    assert intent_handover_reasons(intent, message="问问进度", profile=profile) == [
        "意图识别标记为应转人工"
    ]
