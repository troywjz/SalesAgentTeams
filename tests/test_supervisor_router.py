from app.conversation import ConversationState
from app.graph.nodes import _intent_transfer_reason, route_after_knowledge
from app.graph.routing_rules import (
    has_strong_handover_keyword,
    intent_handover_reasons,
    load_routing_rules,
)
from app.graph.supervisor_router import decide_supervisor_route


def test_supervisor_router_does_not_call_llm_for_manual_control() -> None:
    state = ConversationState(session_id="test", transfer_flag=True)

    decision = decide_supervisor_route("你好", state)

    assert decision.requires_llm is False
    assert decision.route == "manual_control"
    assert not any(decision.run_agents.values())


def test_supervisor_router_forces_handover_for_risk_keywords() -> None:
    decision = decide_supervisor_route("我要退款，不然就投诉", ConversationState(session_id="test"))

    assert decision.route == "force_handover"
    assert not any(decision.run_agents.values())


def test_supervisor_router_keeps_agents_separate_for_full_auto() -> None:
    decision = decide_supervisor_route(
        "我预算三千，想了解产品价格和服务区别",
        ConversationState(session_id="test"),
    )

    assert decision.route == "full_auto"
    assert decision.run_agents["intent"] is True
    assert decision.run_agents["sop"] is True
    assert decision.run_agents["knowledge"] is True
    assert decision.run_agents["conversation"] is True
    assert decision.run_agents["safety"] is True
    assert decision.run_agents["memory_update"] is True


def test_partial_knowledge_insufficiency_can_continue_conversation() -> None:
    route = route_after_knowledge(
        {
            "sop": {"should_transfer": False},
            "knowledge_output": {
                "facts": ["初级会计考试每年一次"],
                "missing_info": ["报名条件需要人工确认"],
                "knowledge_sufficiency": "insufficient",
            },
        }
    )

    assert route == "conversation"


def test_empty_knowledge_insufficiency_routes_to_handover() -> None:
    route = route_after_knowledge(
        {
            "sop": {"should_transfer": False},
            "knowledge_output": {
                "facts": [],
                "matched_skus": [],
                "missing_info": ["报名条件需要人工确认"],
                "knowledge_sufficiency": "insufficient",
            },
        }
    )

    assert route == "handover"


def test_routing_rules_can_be_loaded_from_json(tmp_path) -> None:
    path = tmp_path / "routing_rules.json"
    path.write_text(
        '{"routing_rules":{"strong_handover_keywords":["找老板"],"small_talk_max_chars":5}}',
        encoding="utf-8",
    )

    rules = load_routing_rules(path)

    assert rules.strong_handover_keywords == ("找老板",)
    assert rules.small_talk_max_chars == 5
    assert has_strong_handover_keyword("我现在要找老板", rules) is True


def test_intent_handover_reason_records_all_triggered_fields() -> None:
    intent = {
        "should_transfer": True,
        "intent_category": "high_intent",
        "purchase_intent": "high",
        "emotion": "impatient",
    }

    assert intent_handover_reasons(intent) == [
        "意图识别标记为应转人工",
        "意图类别=high_intent",
        "购买意向=high",
        "情绪=impatient",
    ]
    assert _intent_transfer_reason(intent) == (
        "意图识别触发转人工：意图识别标记为应转人工、意图类别=high_intent、购买意向=high、情绪=impatient"
    )
