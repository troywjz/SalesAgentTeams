from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app.llm.base import ChatMessage, LLMCallAttempt, LLMResponse


class DemoLLMClient:
    """无需外部 API 的确定性模型，用于 Windows 功能演示。"""

    provider = "demo"
    model = "sales-agent-demo"

    def __init__(self, *, delay_ms: int = 60) -> None:
        self.delay_ms = max(0, delay_ms)

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: str | None = None,
    ) -> LLMResponse:
        started = time.perf_counter()
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)

        system_prompt = next(
            (message.content for message in messages if message.role == "system"),
            "",
        )
        user_prompt = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        agent_name = _extract_agent_name(system_prompt)
        context = _extract_context(user_prompt)
        payload = _run_demo_agent(agent_name, context)
        content = json.dumps(payload, ensure_ascii=False)
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        request_json = {
            "agent_name": agent_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        response_json = {"content": payload}
        attempt = LLMCallAttempt(
            provider=self.provider,
            model=self.model,
            api_url="local://demo",
            protocol="local_demo",
            attempt_index=1,
            success=True,
            elapsed_ms=elapsed_ms,
            request_json=request_json,
            response_json=response_json,
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return LLMResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            raw_response=response_json,
            usage=attempt.usage,
            call_attempts=[attempt],
        )


def _extract_agent_name(system_prompt: str) -> str:
    match = re.search(r"\[agent_name:([a-z_]+)]", system_prompt)
    return match.group(1) if match else "conversation_agent"


def _extract_context(user_prompt: str) -> dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", user_prompt, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _run_demo_agent(agent_name: str, context: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "intent_agent": _intent_output,
        "sop_agent": _sop_output,
        "knowledge_agent": _knowledge_output,
        "conversation_agent": _conversation_output,
        "safety_agent": _safety_output,
        "memory_agent": _memory_output,
    }
    return handlers.get(agent_name, _conversation_output)(context)


def _intent_output(context: dict[str, Any]) -> dict[str, Any]:
    message = str(context.get("message") or "").strip()
    if any(word in message for word in ("报名", "付款", "购买", "合同", "链接", "联系老师")):
        category, purchase, emotion = "high_intent", "high", "positive"
    elif any(word in message for word in ("价格", "多少钱", "费用", "优惠", "预算")):
        category, purchase, emotion = "price_inquiry", "medium", "neutral"
    elif any(word in message for word in ("贵", "担心", "犹豫", "再看看", "对比", "跟不上")):
        category, purchase, emotion = "objection", "medium", "skeptical"
    elif any(word in message for word in ("课程", "学习", "适合", "内容", "提升", "零基础")):
        category, purchase, emotion = "course_inquiry", "medium", "neutral"
    elif any(word in message.lower() for word in ("你好", "您好", "hi", "hello")):
        category, purchase, emotion = "greeting", "low", "neutral"
    else:
        category, purchase, emotion = "course_inquiry", "low", "neutral"
    return {
        "intent_category": category,
        "purchase_intent": purchase,
        "emotion": emotion,
        "confidence": 0.91,
        "reason": "演示模型根据客户消息中的需求和意向信号完成判断",
    }


def _sop_output(context: dict[str, Any]) -> dict[str, Any]:
    current = str(context.get("current_stage") or "开场")
    options = [str(item) for item in context.get("stage_options") or [] if str(item)]
    intent = context.get("intent") if isinstance(context.get("intent"), dict) else {}
    category = str(intent.get("intent_category") or "")
    target = current
    if category == "greeting":
        target = _pick_stage(options, "破冰", current)
    elif category in {"course_inquiry", "objection"}:
        target = _pick_stage(options, "探需", current)
    elif category == "price_inquiry":
        target = _pick_stage(options, "价值", current)
    elif category == "high_intent":
        target = _pick_stage(options, "报价", current)
    should_transfer = category == "high_intent"
    return {
        "current_stage": target,
        "next_action": "确认客户的使用场景和优先目标，再给出匹配方案",
        "should_transfer": should_transfer,
        "reason": "根据本轮意图和当前阶段推进销售流程",
    }


def _pick_stage(options: list[str], keyword: str, fallback: str) -> str:
    return next((stage for stage in options if keyword in stage), fallback)


def _knowledge_output(context: dict[str, Any]) -> dict[str, Any]:
    skus = context.get("skus") if isinstance(context.get("skus"), list) else []
    matched = []
    facts: list[str] = []
    for sku in skus[:2]:
        if not isinstance(sku, dict):
            continue
        matched.append(
            {
                "sku_name": sku.get("sku_name") or "演示方案",
                "sku_type": sku.get("sku_type") or "course",
                "list_price_yuan": sku.get("list_price_yuan") or "",
                "deal_price_yuan": sku.get("deal_price_yuan") or "",
                "currency": sku.get("currency") or "CNY",
                "suitable_for": sku.get("target_users") or [],
            }
        )
        facts.extend(str(item) for item in (sku.get("selling_points") or [])[:2])
    if not facts:
        facts = [
            "课程包含场景诊断、方法讲解和实战练习",
            "具体方案需要结合客户基础和使用目标确认",
        ]
    return {
        "matched_skus": matched,
        "facts": facts[:6],
        "policy_notes": ["价格与优惠以人工最终确认为准"],
        "missing_info": [],
        "knowledge_sufficiency": "sufficient",
    }


def _conversation_output(context: dict[str, Any]) -> dict[str, Any]:
    message = str(context.get("message") or "").strip()
    intent = context.get("intent") if isinstance(context.get("intent"), dict) else {}
    category = str(intent.get("intent_category") or "")
    references = context.get("sales_case_references") or []
    if context.get("rewrite_required"):
        reply = "可以，我先按你的实际情况把可选方案梳理清楚，具体价格和权益再由顾问确认。"
    elif category == "greeting":
        reply = "你好，很高兴认识你。你目前更想提升日常办公效率，还是解决某个具体工作场景？"
    elif category == "price_inquiry":
        reply = "价格需要结合你选择的方案确认。我先了解一下你的使用目标和预算范围，再帮你缩小选择，可以吗？"
    elif category == "objection" or any(word in message for word in ("担心", "跟不上", "太贵")):
        reply = "这个顾虑很实际。我们可以先从你最常用的场景入手，不需要一次掌握全部内容。你现在最想先解决哪类工作任务？"
    elif category == "high_intent":
        reply = "可以，我已经记录你的意向。接下来由顾问和你确认方案、价格及付款细节。"
    else:
        reply = "可以，先从你的实际工作场景来判断会更准确。你目前最希望提效的是文档、数据处理，还是日常沟通？"
    strategy = "参考了案例中的顾虑承接与单问题推进" if references else "按当前 SOP 直接推进"
    return {"thinking": strategy, "final_reply": reply}


def _safety_output(context: dict[str, Any]) -> dict[str, Any]:
    draft = str(context.get("draft_reply") or "").strip()
    sop = context.get("sop_decision") if isinstance(context.get("sop_decision"), dict) else {}
    message = str(context.get("message") or "")
    if sop.get("should_transfer") or any(word in message for word in ("付款", "合同", "开发票")):
        return {
            "action": "transfer",
            "approved_reply": "",
            "revised_reply": "",
            "transfer_reason": "客户进入交易确认阶段，需要人工顾问接管",
            "handover_summary": "客户已表达明确交易意向，请跟进方案和付款细节。",
            "risks": [],
        }
    risky = any(word in draft for word in ("保证就业", "保证涨薪", "包过", "最后一天优惠"))
    if risky:
        return {
            "action": "revise",
            "approved_reply": "",
            "revised_reply": "我可以结合你的实际情况说明方案，具体效果取决于后续学习和实践。",
            "transfer_reason": "",
            "handover_summary": "",
            "risks": ["包含不当效果承诺"],
        }
    return {
        "action": "pass",
        "approved_reply": draft,
        "revised_reply": "",
        "safe_reply": draft,
        "customer_reply": draft,
        "transfer_reason": "",
        "handover_summary": "",
        "risks": [],
    }


def _memory_output(context: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("current_profile")
    if not isinstance(profile, dict):
        profile = {}
    profile = dict(profile)
    exchange = context.get("new_exchange")
    if isinstance(exchange, dict):
        message = str(exchange.get("customer") or exchange.get("message") or "")
    else:
        message = str(context.get("message") or exchange or "")
    if "零基础" in message:
        profile["education"] = profile.get("education") or "零基础"
        profile["concerns"] = list(dict.fromkeys([*(profile.get("concerns") or []), "担心学习门槛"]))
    if any(word in message for word in ("提升", "效率", "办公")):
        profile["learning_goal"] = "提升 AI 办公效率"
    purchase = "high" if any(word in message for word in ("报名", "付款", "购买")) else "medium"
    profile["purchase_intent"] = purchase
    summary = str(context.get("current_memory") or "").strip()
    addition = f"客户本轮关注：{message[:80]}" if message else "已完成本轮客户需求确认"
    return {
        "history_summary": "；".join(item for item in (summary, addition) if item)[-1200:],
        "customer_profile": profile,
        "profile_updates": ["已更新学习目标与购买意向"],
    }
