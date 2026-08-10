from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.time import beijing_now
from app.core.config import get_settings
from app.db.models import (
    ConversationFollowupJob,
    ConversationSession,
    ConversationSOPState,
    ConversationTurn,
    CustomerRecord,
    LLMCall,
    Message,
    NodeInvocation,
    ScheduledMessageTask,
)
from app.db.session import SessionLocal
from app.repositories import ChatRepository


DEMO_SESSION_PREFIX = "demo-session-"


def seed_demo_environment() -> None:
    """校验目标库后，安全导入公开知识和演示业务数据。"""
    settings = get_settings()
    _assert_demo_database_target(settings)

    from app.knowledge.importer import import_knowledge_sources

    import_knowledge_sources(
        use_example_sources=True,
        # 只导入仓库中的公开 CSV 示例，不读取任何私有 PDF 或历史聊天记录。
        include_safety_rules=True,
    )
    ensure_demo_data()


def ensure_demo_data() -> None:
    """幂等写入可公开展示的样例会话和运行指标。"""
    settings = get_settings()
    _assert_demo_database_target(settings)
    with SessionLocal() as db:
        ChatRepository(db).ensure_default_sales_user()
        exists = db.scalar(
            select(ConversationSession.session_id).where(
                ConversationSession.session_id == f"{DEMO_SESSION_PREFIX}001"
            )
        )
        if not exists:
            _seed_dashboard_data(db)
        db.commit()


def _assert_demo_database_target(settings) -> None:
    database_name = (make_url(settings.database_url).database or "").lower()
    if database_name != "sales_agent_demo":
        raise RuntimeError(
            "拒绝向非 Demo 数据库写入演示数据。Windows Demo 只使用 sales_agent_demo。"
        )


def _seed_dashboard_data(db) -> None:
    now = beijing_now()
    stages = ["开场", "破冰", "探需扩需A", "探需扩需B", "价值塑造", "方案引导", "报价", "报价", "方案引导", "探需扩需C"]
    customers = [
        ("林晓", "提升日常文档效率", "medium", "零基础，担心跟不上"),
        ("陈思远", "自动整理经营数据", "high", "关注方案价格"),
        ("周宁", "优化团队协作", "medium", "时间安排紧张"),
        ("何然", "减少重复录入", "low", "仍在了解"),
        ("宋琪", "提升汇报效率", "medium", "希望看到实际案例"),
        ("赵峰", "搭建部门工作流", "high", "需要确认交付范围"),
        ("杜悦", "提高表格处理效率", "medium", "预算待确认"),
        ("许宁", "学习 AI 办公方法", "high", "准备报名"),
        ("顾晨", "优化客户沟通", "medium", "对比多个方案"),
        ("唐可", "形成个人自动化流程", "low", "暂无明确时间"),
    ]
    for index, (name, goal, intent, concern) in enumerate(customers, start=1):
        session_id = f"{DEMO_SESSION_PREFIX}{index:03d}"
        customer_id = f"demo-customer-{index:03d}"
        created_at = now - timedelta(hours=index * 7 if index < 4 else index * 14)
        transfer = index == 8
        session = ConversationSession(
            session_id=session_id,
            customer_id=customer_id,
            sales_id="sales-wangjie",
            sales_name="王杰",
            current_stage=stages[index - 1],
            message_count=2 + index % 4,
            transfer_flag=transfer,
            transfer_reason="客户已进入交易确认阶段" if transfer else "",
            history_summary=f"客户希望{goal}，当前顾虑：{concern}。",
            latest_turn_id=f"demo-turn-{index:03d}",
            created_at=created_at,
            updated_at=created_at + timedelta(minutes=18),
        )
        db.add(session)
        db.add(
            CustomerRecord(
                customer_id=customer_id,
                session_id=session_id,
                name=name,
                education="零基础" if index in {1, 4, 7} else "有基础",
                work_status="在职",
                learning_goal=goal,
                budget="待确认" if index % 3 else "2000元以内",
                urgency="近期" if intent == "high" else "一般",
                concerns_json=json.dumps([concern], ensure_ascii=False),
                purchase_intent=intent,
                created_at=created_at,
                updated_at=created_at + timedelta(minutes=18),
            )
        )
        db.add(
            ConversationSOPState(
                session_id=session_id,
                customer_id=customer_id,
                sales_id="sales-wangjie",
                sales_name="王杰",
                current_stage=stages[index - 1],
                followup_count=1 if index in {3, 6} else 0,
                status="handover" if transfer else "active",
                last_customer_message_at=created_at + timedelta(minutes=4),
                last_sales_message_at=created_at + timedelta(minutes=5),
                created_at=created_at,
                updated_at=created_at + timedelta(minutes=18),
            )
        )
        turn_id = f"demo-turn-{index:03d}"
        db.add(
            ConversationTurn(
                turn_id=turn_id,
                session_id=session_id,
                customer_id=customer_id,
                sales_id="sales-wangjie",
                sales_name="王杰",
                turn_index=1,
                trigger_type="customer_message",
                status="sent" if not transfer else "handover",
                input_message_ids_json=json.dumps([f"demo-message-{index:03d}-u"]),
                client_message_ids_json="[]",
                input_text=concern,
                reply_text="我先结合你的实际场景帮你判断，再给出更匹配的建议。" if not transfer else "",
                started_at=created_at + timedelta(minutes=4),
                completed_at=created_at + timedelta(minutes=4, milliseconds=420 + index * 35),
                created_at=created_at + timedelta(minutes=4),
                updated_at=created_at + timedelta(minutes=5),
            )
        )
        db.add(
            Message(
                message_id=f"demo-message-{index:03d}-u",
                session_id=session_id,
                turn_id=turn_id,
                customer_id=customer_id,
                sales_id="sales-wangjie",
                sales_name="王杰",
                role="user",
                sender_type="customer",
                content=concern,
                created_at=created_at + timedelta(minutes=4),
            )
        )
        if not transfer:
            db.add(
                Message(
                    message_id=f"demo-message-{index:03d}-a",
                    session_id=session_id,
                    turn_id=turn_id,
                    customer_id=customer_id,
                    sales_id="sales-wangjie",
                    sales_name="王杰",
                    role="assistant",
                    sender_type="salesagent",
                    content="我先结合你的实际场景帮你判断，再给出更匹配的建议。",
                    created_at=created_at + timedelta(minutes=5),
                )
            )
        _seed_agent_metrics(db, index, session_id, turn_id, created_at)

    db.add(
        ConversationFollowupJob(
            job_id="demo-followup-sent",
            session_id=f"{DEMO_SESSION_PREFIX}003",
            customer_id="demo-customer-003",
            sales_id="sales-wangjie",
            sales_name="王杰",
            stage="探需扩需A",
            status="sent",
            reference_script="你目前更关注投入时间，还是实际使用效果？",
            timeout_action="next",
            scheduled_at=now - timedelta(hours=1),
            sent_message_id="demo-followup-message",
            sent_at=now - timedelta(minutes=55),
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=55),
        )
    )
    db.add(
        ScheduledMessageTask(
            task_id="demo-scheduled-sent",
            name="演示回访任务",
            status="sent",
            enabled=True,
            scheduled_at=now - timedelta(hours=2),
            target_mode="manual",
            selected_session_ids_json=json.dumps([f"{DEMO_SESSION_PREFIX}001"]),
            message_text="你好，之前提到的办公提效场景还有需要我补充的吗？",
            sent_session_ids_json=json.dumps([f"{DEMO_SESSION_PREFIX}001"]),
            created_by_sales_id="sales-wangjie",
            created_by_sales_name="王杰",
            sent_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=2),
        )
    )


def _seed_agent_metrics(db, index: int, session_id: str, turn_id: str, created_at) -> None:
    agents = ("intent_agent", "sop_agent", "knowledge_agent", "sales_case_rag", "conversation_agent", "safety_agent")
    for agent_index, agent_name in enumerate(agents, start=1):
        invocation_id = f"demo-invocation-{index:03d}-{agent_index}"
        output: dict[str, object] = {"status": "ok"}
        provider = "demo"
        model = "sales-agent-demo"
        if agent_name == "sales_case_rag":
            provider = "local"
            model = "sales-case-rag"
            output = {"sales_case_references": []}
        db.add(
            NodeInvocation(
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
                node_name=agent_name,
                model_provider=provider,
                model_name=model,
                elapsed_ms=18 + agent_index * 11 + index,
                success=1,
                input_json=json.dumps({"message": "演示客户消息"}, ensure_ascii=False),
                output_json=json.dumps(output, ensure_ascii=False),
                raw_output=json.dumps(output, ensure_ascii=False),
                created_at=created_at + timedelta(minutes=4, milliseconds=agent_index * 40),
            )
        )
        if agent_name != "sales_case_rag":
            db.add(
                LLMCall(
                    call_id=f"demo-llm-{index:03d}-{agent_index}",
                    session_id=session_id,
                    turn_id=turn_id,
                    node_invocation_id=invocation_id,
                    node_name=agent_name,
                    provider="demo",
                    model_name="sales-agent-demo",
                    api_url="local://demo",
                    protocol="local_demo",
                    attempt_index=1,
                    elapsed_ms=18 + agent_index * 11 + index,
                    success=1,
                    request_json="{}",
                    response_json=json.dumps(output, ensure_ascii=False),
                    usage_json="{}",
                    created_at=created_at + timedelta(minutes=4, milliseconds=agent_index * 40),
                )
            )
if __name__ == "__main__":
    from app.db import init_db

    init_db()
    seed_demo_environment()
    print("Windows Demo 数据已就绪。")
