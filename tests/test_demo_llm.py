import asyncio
import json

from app.llm import ChatMessage, DemoLLMClient


def _chat(agent_name: str, context: dict):
    client = DemoLLMClient(delay_ms=0)
    return asyncio.run(
        client.chat(
            [
                ChatMessage(role="system", content=f"[agent_name:{agent_name}]"),
                ChatMessage(
                    role="user",
                    content=(
                        "上下文 JSON：\n```json\n"
                        + json.dumps(context, ensure_ascii=False)
                        + "\n```"
                    ),
                ),
            ],
            response_format="json",
        )
    )


def test_demo_intent_recognizes_price_question() -> None:
    response = _chat("intent_agent", {"message": "这个课程多少钱，有优惠吗？"})
    output = json.loads(response.content)

    assert output["intent_category"] == "price_inquiry"
    assert output["purchase_intent"] == "medium"
    assert response.provider == "demo"
    assert response.call_attempts[0].success is True


def test_demo_safety_transfers_transaction_request() -> None:
    response = _chat(
        "safety_agent",
        {
            "message": "我现在付款，合同怎么签？",
            "draft_reply": "可以付款。",
            "sop_decision": {"should_transfer": True},
        },
    )

    assert json.loads(response.content)["action"] == "transfer"


def test_demo_conversation_handles_learning_concern() -> None:
    response = _chat(
        "conversation_agent",
        {
            "message": "我是零基础，担心跟不上",
            "intent": {"intent_category": "objection"},
            "sales_case_references": [{"chunk_id": "demo-rag-001"}],
        },
    )

    output = json.loads(response.content)
    assert "Agent" not in output["final_reply"]
    assert "场景" in output["final_reply"]
