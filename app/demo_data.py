from __future__ import annotations

import argparse
import json
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.core.time import beijing_now
from app.core.config import get_settings
from app.db.models import (
    ConversationFollowupJob,
    ConversationMemory,
    ConversationReadCursor,
    ConversationSession,
    ConversationSOPState,
    ConversationTurn,
    CustomerRecord,
    LLMCall,
    Message,
    NodeInvocation,
    LLMCallEmbed,
    LLMSafetyVectorMatch,
    SalesCaseRAGEvent,
    ScheduledMessageTask,
)
from app.db.session import SessionLocal
from app.repositories import ChatRepository


DEMO_SESSION_PREFIX = "demo-session-"


def seed_demo_environment(*, reset: bool = False) -> None:
    """校验目标库后，安全导入公开知识和演示业务数据。"""
    settings = get_settings()
    _assert_demo_database_target(settings)

    from app.knowledge.importer import import_knowledge_sources

    import_knowledge_sources(
        use_example_sources=True,
        # 只导入仓库中的公开 CSV 示例，不读取任何私有 PDF 或历史聊天记录。
        include_safety_rules=True,
    )
    ensure_demo_data(reset=reset)


def ensure_demo_data(*, reset: bool = False) -> None:
    """幂等写入公开样例；显式 reset 只刷新本仓库拥有的固定演示记录。"""
    settings = get_settings()
    _assert_demo_database_target(settings)
    with SessionLocal() as db:
        ChatRepository(db).ensure_default_sales_user()
        if reset:
            _delete_owned_demo_rows(db)
        exists = db.scalar(
            select(ConversationSession.session_id).where(
                ConversationSession.session_id == f"{DEMO_SESSION_PREFIX}001"
            )
        )
        if not exists:
            _seed_dashboard_data(db)
        db.commit()


def _demo_session_ids() -> tuple[str, ...]:
    return tuple(f"{DEMO_SESSION_PREFIX}{index:03d}" for index in range(1, 11))


def _delete_owned_demo_rows(db) -> None:
    """只删除固定 ID 的公开样例，不清空用户在 Demo 库中产生的新会话。"""
    session_ids = _demo_session_ids()
    session_models = (
        LLMSafetyVectorMatch,
        LLMCallEmbed,
        SalesCaseRAGEvent,
        LLMCall,
        NodeInvocation,
        Message,
        ConversationReadCursor,
        ConversationMemory,
        ConversationTurn,
        ConversationFollowupJob,
        ConversationSOPState,
        CustomerRecord,
        ConversationSession,
    )
    for model in session_models:
        db.execute(delete(model).where(model.session_id.in_(session_ids)))
    db.execute(
        delete(ScheduledMessageTask).where(
            ScheduledMessageTask.task_id == "demo-scheduled-sent"
        )
    )


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
        ("林晓", "规范 Word 长文档排版", "medium", "零基础，担心跟不上", "我经常改合同和方案，标题编号总是乱，零基础能学吗？", "可以从样式、编号和目录这三个高频点开始。你现在最常处理的是合同还是项目方案？"),
        ("陈思远", "用 Excel 自动汇总经营数据", "high", "关注方案价格", "每周要合并十几张表，还要做汇总图，有适合的课吗？", "这个场景适合从数据清洗、函数汇总和透视表串起来练。你的原始表字段是否基本一致？"),
        ("周宁", "提升跨部门协作效率", "medium", "时间安排紧张", "工作很忙，一周只能抽两三个小时。", "可以按每次二十分钟拆成任务练习。你更想先解决表格协作，还是汇报材料反复修改？"),
        ("何然", "减少重复复制与录入", "low", "仍在了解", "我每天都在复制粘贴报表，但还不知道该从哪学。", "先找出最重复的一步会更容易见效。你目前是合并多个文件，还是在同一张表里重复录入？"),
        ("宋琪", "提升 PPT 结构化汇报能力", "medium", "希望看到实际案例", "我做的汇报页很多，但领导总说重点不清楚。", "可以先用结论先行和一页一观点重构。你主要做周报、项目复盘，还是提案汇报？"),
        ("赵峰", "建立部门报表工作流", "high", "需要确认交付范围", "我们想让团队统一模板和月报流程，课程能覆盖哪些内容？", "可以先确认人数、现有模板和目标流程，再由顾问核对企业方案边界。你们大约有多少人需要参与？"),
        ("杜悦", "掌握 Excel 函数与透视表", "medium", "预算待确认", "函数和透视表我都会一点，想系统提升，预算还没定。", "可以先用一份真实工作表判断薄弱点，再匹配专项课。你更常卡在跨表匹配还是汇总分析？"),
        ("许宁", "学习 AI 办公协作方法", "high", "准备报名", "我想现在报名，付款和发票怎么处理？", "付款、合同和发票需要人工顾问按当前政策确认。我已整理你的需求并转交顾问继续处理。"),
        ("顾晨", "提高客户方案沟通效率", "medium", "对比多个方案", "我在比较 Excel 专项和综合训练营，不知道哪个更适合。", "如果痛点集中在数据处理，专项课更聚焦；如果还包括 Word 和 PPT，综合训练营更完整。你最急的是哪类任务？"),
        ("唐可", "形成个人办公自动化流程", "low", "暂无明确时间", "我想学自动化，但暂时没有明确开始时间。", "可以先做一次重复任务清单，不必马上决定课程。你愿意先记下本周最耗时的三个办公任务吗？"),
    ]
    for index, (name, goal, intent, concern, customer_message, reply_text) in enumerate(customers, start=1):
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
                input_text=customer_message,
                reply_text=reply_text if not transfer else "",
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
                content=customer_message,
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
                    content=reply_text,
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
                input_json=json.dumps({"message": "公开 To C 网络销售演示消息"}, ensure_ascii=False),
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
    parser = argparse.ArgumentParser(description="初始化独立的 To C 网络销售 Demo 数据。")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="只刷新 demo-session-001 至 010 等固定公开样例，不删除其他 Demo 会话。",
    )
    arguments = parser.parse_args()
    from app.db import init_db

    init_db()
    seed_demo_environment(reset=arguments.reset)
    print("To C 网络销售 Demo 数据已就绪。")
