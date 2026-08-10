import asyncio

from app.conversation import CustomerProfile
from app.graph.sales_graph import build_sales_graph
from app.llm import DemoLLMClient
from app.sales_rag import SalesCaseRAGReference


class DemoKnowledgeLoader:
    stages = ["开场", "破冰", "探需扩需", "价值塑造", "方案引导", "报价"]

    def load_context(self):
        return {
            "sales_sop": {},
            "safety_rules": {},
            "skus": [],
            "faq": "",
            "knowledge_catalog": [{"knowledge_key": "skus"}],
        }

    def list_sop_stages(self, *, include_terminal=False):
        return self.stages

    def query_sop_docs(self, **_):
        return {"探需扩需": [{"任务目标": "确认客户场景和目标"}]}

    def query_context(self, **_):
        return {
            "selected_knowledge_sources": ["skus", "faq"],
            "skus": [
                {
                    "sku_name": "AI 办公提效训练营",
                    "sku_type": "course",
                    "target_users": ["零基础职场人"],
                    "selling_points": ["场景化练习", "任务模板"],
                    "list_price_yuan": "1999",
                    "currency": "CNY",
                }
            ],
            "faq": "零基础可以从常见办公任务开始学习。",
            "sop_docs": {},
        }

    def load_safety_rules(self):
        return {}


class DemoRAGService:
    async def retrieve(self, **_):
        return [
            SalesCaseRAGReference(
                chunk_id="demo-rag-001",
                conversation_hash="demo",
                customer_text="零基础担心跟不上",
                sales_reply="先从一个常用场景开始。",
                context_before="客户关注学习门槛",
                quality_score=0.93,
                similarity=0.81,
                tags=["零基础", "顾虑处理"],
            )
        ]


def test_demo_graph_completes_multi_agent_reply() -> None:
    graph = build_sales_graph(
        DemoLLMClient(delay_ms=0),
        knowledge_loader=DemoKnowledgeLoader(),
        sales_case_rag_service=DemoRAGService(),
        enable_checkpoint=False,
        include_memory_update=True,
    )
    result = asyncio.run(
        graph.ainvoke(
            {
                "message": "我是零基础，担心跟不上，想提升办公效率",
                "session_id": "graph-demo",
                "turn_id": "turn-demo",
                "customer_id": "customer-demo",
                "current_stage": "开场",
                "customer_profile": CustomerProfile(),
                "history_summary": "",
                "message_count": 0,
                "transfer_flag": False,
                "transfer_reason": "",
                "runs": [],
            }
        )
    )

    assert result["reply"]
    assert result["sent_reply"] is True
    assert result["sales_case_references"][0]["chunk_id"] == "demo-rag-001"
    assert result["current_stage"] == "探需扩需"
    run_names = {run.agent_name for run in result["runs"]}
    assert {
        "intent_agent",
        "sop_agent",
        "knowledge_agent",
        "sales_case_rag",
        "conversation_agent",
        "safety_agent",
        "memory_agent",
    }.issubset(run_names)
