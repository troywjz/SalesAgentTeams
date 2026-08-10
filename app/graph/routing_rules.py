from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT


ROUTING_RULES_PATH = PROJECT_ROOT / "data" / "business" / "routing_rules.json"
ROUTING_RULES_EXAMPLE_PATH = PROJECT_ROOT / "data" / "business" / "routing_rules.example.json"


@dataclass(frozen=True)
class RoutingRules:
    """确定性路由规则配置。

    这里集中管理不需要 LLM 的关键词和枚举规则，方便单独修改。
    注意：这些规则只负责快速路由，不替代 SOPAgent / SafetyAgent 的业务判断。
    """

    strong_handover_keywords: tuple[str, ...] = (
        "投诉",
        "举报",
        "诈骗",
        "骗子",
        "退款",
        "退费",
        "拉黑",
        "报警",
        "律师",
        "起诉",
        "立刻报名",
        "现在付款",
        "马上买",
        "转人工",
        "人工",
    )
    extreme_emotion_keywords: tuple[str, ...] = (
        "气死",
        "崩溃",
        "烦死",
        "别烦我",
        "太差了",
        "垃圾",
        "滚",
    )
    knowledge_keywords: tuple[str, ...] = (
        "多少钱",
        "价格",
        "费用",
        "优惠",
        "折扣",
        "套餐",
        "产品",
        "课程",
        "服务",
        "包含",
        "区别",
        "对比",
        "适合",
        "报名",
        "退款",
        "协议",
        "合同",
        "发票",
        "证书",
        "上课",
        "交付",
        "时间",
    )
    profile_update_keywords: tuple[str, ...] = (
        "我是",
        "我在",
        "我想",
        "我希望",
        "我准备",
        "预算",
        "年龄",
        "学历",
        "工作",
        "目标",
        "基础",
        "经验",
        "急",
        "担心",
    )
    small_talk_keywords: tuple[str, ...] = (
        "你好",
        "您好",
        "在吗",
        "有人吗",
        "谢谢",
        "好的",
        "嗯",
        "行",
    )
    small_talk_max_chars: int = 20
    intent_handover_categories: tuple[str, ...] = ("high_intent",)
    intent_handover_purchase_intents: tuple[str, ...] = ("high",)
    intent_handover_emotions: tuple[str, ...] = ("impatient",)
    intent_direct_reply_categories: tuple[str, ...] = ("greeting", "off_topic")
    intent_context_categories: tuple[str, ...] = (
        "course_inquiry",
        "price_inquiry",
        "objection",
    )
    safety_max_review_count: int = 3
    knowledge_sufficient_values: tuple[str, ...] = (
        "sufficient",
        "enough",
        "true",
        "yes",
        "充足",
    )
    knowledge_insufficient_values: tuple[str, ...] = (
        "insufficient",
        "not_enough",
        "false",
        "no",
        "不足",
    )


def _tuple_setting(
    data: dict[str, Any],
    key: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        raise TypeError(f"{key} 必须是字符串数组")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _int_setting(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{key} 必须是整数") from exc


def load_routing_rules(path: Path | None = None) -> RoutingRules:
    """读取可手动维护的确定性路由规则。

    优先读取本地私有配置 ``data/business/routing_rules.json``；
    如果不存在，则读取可提交的示例配置 ``routing_rules.example.json``；
    示例也不存在时回退到代码默认值，保证测试和最小运行不被阻断。
    """
    defaults = RoutingRules()
    config_path = path
    if config_path is None:
        config_path = ROUTING_RULES_PATH if ROUTING_RULES_PATH.exists() else ROUTING_RULES_EXAMPLE_PATH
    if not config_path.exists():
        return defaults

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"读取路由规则配置失败：{config_path}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError(f"路由规则配置必须是 JSON 对象：{config_path}")
    data = raw.get("routing_rules", raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"routing_rules 必须是 JSON 对象：{config_path}")

    return RoutingRules(
        strong_handover_keywords=_tuple_setting(
            data,
            "strong_handover_keywords",
            defaults.strong_handover_keywords,
        ),
        extreme_emotion_keywords=_tuple_setting(
            data,
            "extreme_emotion_keywords",
            defaults.extreme_emotion_keywords,
        ),
        knowledge_keywords=_tuple_setting(
            data,
            "knowledge_keywords",
            defaults.knowledge_keywords,
        ),
        profile_update_keywords=_tuple_setting(
            data,
            "profile_update_keywords",
            defaults.profile_update_keywords,
        ),
        small_talk_keywords=_tuple_setting(
            data,
            "small_talk_keywords",
            defaults.small_talk_keywords,
        ),
        small_talk_max_chars=_int_setting(
            data,
            "small_talk_max_chars",
            defaults.small_talk_max_chars,
        ),
        intent_handover_categories=_tuple_setting(
            data,
            "intent_handover_categories",
            defaults.intent_handover_categories,
        ),
        intent_handover_purchase_intents=_tuple_setting(
            data,
            "intent_handover_purchase_intents",
            defaults.intent_handover_purchase_intents,
        ),
        intent_handover_emotions=_tuple_setting(
            data,
            "intent_handover_emotions",
            defaults.intent_handover_emotions,
        ),
        intent_direct_reply_categories=_tuple_setting(
            data,
            "intent_direct_reply_categories",
            defaults.intent_direct_reply_categories,
        ),
        intent_context_categories=_tuple_setting(
            data,
            "intent_context_categories",
            defaults.intent_context_categories,
        ),
        safety_max_review_count=_int_setting(
            data,
            "safety_max_review_count",
            defaults.safety_max_review_count,
        ),
        knowledge_sufficient_values=_tuple_setting(
            data,
            "knowledge_sufficient_values",
            defaults.knowledge_sufficient_values,
        ),
        knowledge_insufficient_values=_tuple_setting(
            data,
            "knowledge_insufficient_values",
            defaults.knowledge_insufficient_values,
        ),
    )


@lru_cache
def get_routing_rules() -> RoutingRules:
    return load_routing_rules()


DEFAULT_ROUTING_RULES = get_routing_rules()


def normalize_text(value: str) -> str:
    """转小写并移除空白，避免关键词被空格或换行拆开后无法命中。"""
    return "".join(str(value or "").lower().split())


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """检查文本是否包含任一关键词。"""
    return any(keyword.lower() in text for keyword in keywords)


def has_strong_handover_keyword(
    message: str,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    return contains_any(normalize_text(message), rules.strong_handover_keywords)


def has_extreme_emotion_keyword(
    message: str,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    return contains_any(normalize_text(message), rules.extreme_emotion_keywords)


def looks_like_knowledge_request(
    message: str,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    return contains_any(normalize_text(message), rules.knowledge_keywords)


def has_profile_signal(
    message: str,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    return contains_any(normalize_text(message), rules.profile_update_keywords)


def is_small_talk(
    message: str,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    text = normalize_text(message)
    if len(text) > rules.small_talk_max_chars:
        return False
    return contains_any(text, rules.small_talk_keywords)


# 已报名/已购课状态特征词（必须匹配"已"字头，避免误伤"考虑报名/准备进班/报名推进中"等未成交状态）。
ENROLLED_MARKERS: tuple[str, ...] = (
    "已报名", "已购买", "已购", "已缴费", "已交费", "已付费", "已付款", "已支付",
    "已交定金", "已开通", "已激活", "已进班", "学习中",
)

# 新购买信号（已报名客户再次出现购买意图时的关键词，命中则仍按高意向转人工）。
NEW_PURCHASE_SIGNAL_KEYWORDS: tuple[str, ...] = (
    "付款", "支付", "缴费", "学费", "转账", "定金", "下单", "购买",
    "报名", "链接", "二维码", "收款码", "微信", "支付宝",
    "再报", "加报", "增报", "续费", "续报", "转介绍", "推荐给",
)


def customer_is_enrolled(profile: Any) -> bool:
    """画像显示客户已报名/已购课。兼容 CustomerProfile 对象或 dict。"""
    if not profile:
        return False
    value = (
        profile.get("purchase_intent")
        if isinstance(profile, dict)
        else getattr(profile, "purchase_intent", "")
    )
    text = str(value or "").strip()
    return any(marker in text for marker in ENROLLED_MARKERS)


def has_new_purchase_signal(message: str) -> bool:
    """消息中是否出现新的购买/付款/转介绍信号。"""
    return contains_any(normalize_text(message), NEW_PURCHASE_SIGNAL_KEYWORDS)


def intent_should_handover(
    intent: dict[str, Any],
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
    *,
    message: str = "",
    profile: Any = None,
) -> bool:
    return bool(intent_handover_reasons(intent, rules, message=message, profile=profile))


def intent_handover_reasons(
    intent: dict[str, Any],
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
    *,
    message: str = "",
    profile: Any = None,
) -> list[str]:
    """返回意图识别触发转人工的确定性依据。

    该函数与 ``intent_should_handover`` 共用同一套规则，供正式链路在
    转人工时记录可追溯原因，避免只留下泛化的调度兜底文案。

    已报名/已购课客户的日常跟进消息（学习进度、补课、资料、闲聊等）即使
    被意图识别误判为 high_intent / 高购买意向，只要消息中不含新的购买信号
    就不转人工，避免把已成交客户的日常沟通误甩给真人。
    """
    category = str(intent.get("intent_category") or "").lower()
    purchase_intent = str(intent.get("purchase_intent") or "").lower()
    emotion = str(intent.get("emotion") or "").lower()
    reasons: list[str] = []
    if bool(intent.get("should_transfer")):
        reasons.append("意图识别标记为应转人工")
    if category in rules.intent_handover_categories:
        reasons.append(f"意图类别={category}")
    if purchase_intent in rules.intent_handover_purchase_intents:
        reasons.append(f"购买意向={purchase_intent}")
    if emotion in rules.intent_handover_emotions:
        reasons.append(f"情绪={emotion}")
    # 已报名客户兜底复核：仅过滤由意图类别/购买意向触发的理由，
    # should_transfer 与情绪 impatient 触发的转人工不受影响。
    if reasons and customer_is_enrolled(profile) and not has_new_purchase_signal(message):
        reasons = [
            reason
            for reason in reasons
            if not (reason.startswith("意图类别=") or reason.startswith("购买意向="))
        ]
    return reasons


def intent_should_direct_reply(
    intent: dict[str, Any],
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    category = str(intent.get("intent_category") or "").lower()
    return category in rules.intent_direct_reply_categories


def intent_needs_context(
    intent: dict[str, Any],
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    category = str(intent.get("intent_category") or "").lower()
    return category in rules.intent_context_categories


def safety_retry_exceeded(
    retry_count: int,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool:
    return retry_count >= rules.safety_max_review_count


def explicit_knowledge_sufficiency(
    value: Any,
    rules: RoutingRules = DEFAULT_ROUTING_RULES,
) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in rules.knowledge_sufficient_values:
            return True
        if normalized in rules.knowledge_insufficient_values:
            return False
    return bool(value)
