from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.db.models import (
    ConversationFollowupJob,
    ConversationSession,
    ConversationTurn,
    CustomerRecord,
    KnowledgeSOP,
    LLMCall,
    Message,
    NodeInvocation,
    SalesCaseRAGEvent,
    ScheduledMessageTask,
)


RANGE_OPTIONS = {
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
}

INTENT_LABELS = {
    "low": "低意向",
    "medium": "中意向",
    "high": "高意向",
}

MESSAGE_SOURCE_LABELS = {
    "customer": "客户消息",
    "salesagent": "AI 回复",
    "human": "人工回复",
    "system": "系统消息",
}


class AdminDashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(self) -> dict[str, Any]:
        now = beijing_now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sessions = self._sessions_since(start)
        messages = self._messages_since(start)
        turns = self._turns_since(start)
        node_runs = self._node_invocations_since(start)
        llm_calls = self._llm_calls_since(start)
        rag_hits = self._rag_hits(node_runs)
        safety_triggers = self._safety_triggers(node_runs)
        ai_replies = [msg for msg in messages if msg.sender_type == "salesagent"]
        customer_messages = [msg for msg in messages if msg.sender_type == "customer"]
        successful_turns = [turn for turn in turns if turn.status in {"completed", "success"} or turn.reply_text]
        avg_response_ms = _average(
            int((turn.completed_at - turn.started_at).total_seconds() * 1000)
            for turn in turns
            if turn.started_at and turn.completed_at
        )
        return {
            "generated_at": now.isoformat(),
            "cards": [
                {"key": "new_sessions", "label": "今日新增会话", "value": len(sessions)},
                {"key": "customer_messages", "label": "今日客户消息", "value": len(customer_messages)},
                {"key": "ai_replies", "label": "今日 AI 回复", "value": len(ai_replies)},
                {"key": "handover_sessions", "label": "今日转人工", "value": self._handover_count_since(start)},
                {"key": "high_intent", "label": "高意向客户", "value": self._high_intent_count()},
                {"key": "sop_touch", "label": "今日 SOP 触达", "value": self._followup_sent_count_since(start)},
                {"key": "scheduled_sent", "label": "今日定时发送", "value": self._scheduled_sent_count_since(start)},
                {"key": "ai_success_rate", "label": "AI 回复成功率", "value": _rate(len(successful_turns), len(turns)), "suffix": "%"},
                {"key": "llm_success_rate", "label": "LLM 成功率", "value": _rate(sum(call.success for call in llm_calls), len(llm_calls)), "suffix": "%"},
                {"key": "avg_response_ms", "label": "平均响应耗时", "value": avg_response_ms, "suffix": "ms"},
                {"key": "rag_hits", "label": "销售案例命中", "value": rag_hits},
                {"key": "safety_triggers", "label": "风控触发", "value": safety_triggers},
            ],
        }

    def timeseries(self, range_key: str = "7d", bucket: str | None = None) -> dict[str, Any]:
        range_key = range_key if range_key in RANGE_OPTIONS else "7d"
        delta, default_bucket = RANGE_OPTIONS[range_key]
        bucket = bucket if bucket in {"hour", "day"} else default_bucket
        end = beijing_now()
        start = _floor_time(end - delta, bucket)
        buckets = _bucket_labels(start, end, bucket)
        counters: dict[str, Counter[str]] = {
            "new_sessions": Counter(),
            "customer_messages": Counter(),
            "ai_replies": Counter(),
            "human_replies": Counter(),
            "handover": Counter(),
            "scheduled_sent": Counter(),
            "sop_touch": Counter(),
            "safety_triggers": Counter(),
            "sales_rag_hits": Counter(),
        }
        elapsed_by_bucket: dict[str, list[int]] = defaultdict(list)

        for session in self._sessions_since(start):
            counters["new_sessions"][_bucket_key(session.created_at, bucket)] += 1

        for session in self._handover_sessions_since(start):
            if session.transfer_flag:
                counters["handover"][_bucket_key(session.updated_at, bucket)] += 1

        for message in self._messages_since(start):
            key = _bucket_key(message.created_at, bucket)
            if message.sender_type == "customer":
                counters["customer_messages"][key] += 1
            elif message.sender_type == "salesagent":
                counters["ai_replies"][key] += 1
            elif message.sender_type == "human":
                counters["human_replies"][key] += 1

        for task in self._scheduled_tasks_since(start):
            if task.sent_at:
                counters["scheduled_sent"][_bucket_key(task.sent_at, bucket)] += 1

        for job in self._followup_jobs_since(start):
            if job.sent_at:
                counters["sop_touch"][_bucket_key(job.sent_at, bucket)] += 1

        for invocation in self._node_invocations_since(start):
            key = _bucket_key(invocation.created_at, bucket)
            if invocation.node_name == "sales_case_rag" and _has_sales_case_references(invocation.output_json):
                counters["sales_rag_hits"][key] += 1
            if invocation.node_name == "safety" and _safety_action(invocation.output_json) not in {"", "pass"}:
                counters["safety_triggers"][key] += 1
            if invocation.elapsed_ms:
                elapsed_by_bucket[key].append(invocation.elapsed_ms)

        series = [
            _series("new_sessions", "新增会话", buckets, counters["new_sessions"]),
            _series("customer_messages", "客户消息", buckets, counters["customer_messages"]),
            _series("ai_replies", "AI 回复", buckets, counters["ai_replies"]),
            _series("human_replies", "人工回复", buckets, counters["human_replies"]),
            _series("handover", "转人工", buckets, counters["handover"]),
            _series("scheduled_sent", "定时发送", buckets, counters["scheduled_sent"]),
            _series("sop_touch", "SOP 触达", buckets, counters["sop_touch"]),
            _series("safety_triggers", "风控触发", buckets, counters["safety_triggers"]),
            _series("sales_rag_hits", "销售案例命中", buckets, counters["sales_rag_hits"]),
            {
                "key": "avg_node_elapsed_ms",
                "label": "平均节点耗时",
                "points": [
                    {"time": label, "value": _average(elapsed_by_bucket.get(label, []))}
                    for label in buckets
                ],
            },
        ]
        return {"range": range_key, "bucket": bucket, "series": series}

    def distribution(self) -> dict[str, Any]:
        stage_counts = Counter(
            session.current_stage or "未分阶段"
            for session in self.db.execute(select(ConversationSession)).scalars()
        )
        intent_counts = Counter(
            customer.purchase_intent or "low"
            for customer in self.db.execute(select(CustomerRecord)).scalars()
        )
        source_counts = Counter(
            message.sender_type or "system"
            for message in self.db.execute(select(Message)).scalars()
        )
        safety_counts = Counter(
            _safety_action(invocation.output_json) or "pass"
            for invocation in self.db.execute(
                select(NodeInvocation).where(NodeInvocation.node_name == "safety")
            ).scalars()
        )
        return {
            "sop_stage": _counter_items(stage_counts),
            "purchase_intent": [
                {"label": INTENT_LABELS.get(key, key), "value": value}
                for key, value in intent_counts.items()
            ],
            "message_source": [
                {"label": MESSAGE_SOURCE_LABELS.get(key, key or "未知"), "value": value}
                for key, value in source_counts.items()
            ],
            "safety_action": _counter_items(safety_counts),
        }

    def agent_performance(self, range_key: str = "7d") -> dict[str, Any]:
        range_key = range_key if range_key in RANGE_OPTIONS else "7d"
        start = beijing_now() - RANGE_OPTIONS[range_key][0]
        grouped: dict[str, list[NodeInvocation]] = defaultdict(list)
        for invocation in self._node_invocations_since(start):
            grouped[invocation.node_name or "unknown"].append(invocation)
        agents = []
        for node_name, runs in sorted(grouped.items()):
            success = sum(1 for run in runs if run.success)
            agents.append(
                {
                    "node": node_name,
                    "label": node_name,
                    "total": len(runs),
                    "success": success,
                    "failed": len(runs) - success,
                    "success_rate": _rate(success, len(runs)),
                    "avg_elapsed_ms": _average(run.elapsed_ms for run in runs),
                }
            )
        return {"range": range_key, "agents": agents}

    def sop_funnel(self) -> dict[str, Any]:
        stages = self._sop_stage_order()
        sessions = list(self.db.execute(select(ConversationSession)).scalars())
        if not stages:
            stages = _dedupe([session.current_stage for session in sessions if session.current_stage])
        stage_index = {stage: index for index, stage in enumerate(stages)}
        reached_counts = []
        current_counts = Counter(session.current_stage or "未分阶段" for session in sessions)
        for index, stage in enumerate(stages):
            reached = sum(
                1
                for session in sessions
                if stage_index.get(session.current_stage or "", -1) >= index
            )
            previous = reached_counts[-1]["reached"] if reached_counts else reached
            reached_counts.append(
                {
                    "stage": stage,
                    "reached": reached,
                    "current": current_counts.get(stage, 0),
                    "conversion_from_previous": _rate(reached, previous),
                    "conversion_from_first": _rate(reached, reached_counts[0]["reached"] if reached_counts else reached),
                }
            )
        return {"total_sessions": len(sessions), "stages": reached_counts}

    def sales_rag_summary(self, range_key: str = "7d") -> dict[str, Any]:
        start = self._range_start(range_key)
        events = self._sales_rag_events_since(start)
        hit_events = [event for event in events if event.hit_count > 0]
        used_events = [event for event in events if event.used]
        continued = sum(1 for event in used_events if self._has_customer_reply_after(event))
        return {
            "range": range_key if range_key in RANGE_OPTIONS else "7d",
            "cards": [
                {"key": "rag_runs", "label": "RAG 检索次数", "value": len(events)},
                {"key": "rag_hits", "label": "RAG 命中次数", "value": len(hit_events)},
                {"key": "hit_rate", "label": "命中率", "value": _rate(len(hit_events), len(events)), "suffix": "%"},
                {"key": "used_count", "label": "案例使用次数", "value": len(used_events)},
                {"key": "used_rate", "label": "使用率", "value": _rate(len(used_events), len(hit_events)), "suffix": "%"},
                {"key": "avg_score", "label": "平均召回分", "value": round(_average_float(event.avg_score for event in hit_events), 4)},
                {"key": "continue_reply_rate", "label": "使用后继续回复率", "value": _rate(continued, len(used_events)), "suffix": "%"},
            ],
        }

    def sales_rag_timeseries(self, range_key: str = "7d", bucket: str | None = None) -> dict[str, Any]:
        range_key = range_key if range_key in RANGE_OPTIONS else "7d"
        delta, default_bucket = RANGE_OPTIONS[range_key]
        bucket = bucket if bucket in {"hour", "day"} else default_bucket
        end = beijing_now()
        start = _floor_time(end - delta, bucket)
        buckets = _bucket_labels(start, end, bucket)
        grouped: dict[str, list[SalesCaseRAGEvent]] = defaultdict(list)
        for event in self._sales_rag_events_since(start):
            grouped[_bucket_key(event.created_at, bucket)].append(event)

        def bucket_rate(label: str, predicate) -> float:
            events = grouped.get(label, [])
            return _rate(sum(1 for event in events if predicate(event)), len(events))

        def used_rate(label: str) -> float:
            events = grouped.get(label, [])
            hit_events = [event for event in events if event.hit_count > 0]
            return _rate(sum(1 for event in hit_events if event.used), len(hit_events))

        return {
            "range": range_key,
            "bucket": bucket,
            "series": [
                {
                    "key": "hit_rate",
                    "label": "命中率",
                    "points": [{"time": label, "value": bucket_rate(label, lambda event: event.hit_count > 0)} for label in buckets],
                },
                {
                    "key": "used_rate",
                    "label": "使用率",
                    "points": [{"time": label, "value": used_rate(label)} for label in buckets],
                },
                {
                    "key": "avg_score",
                    "label": "平均召回分",
                    "points": [
                        {
                            "time": label,
                            "value": round(_average_float(event.avg_score for event in grouped.get(label, []) if event.hit_count > 0), 4),
                        }
                        for label in buckets
                    ],
                },
            ],
        }

    def sales_rag_comparison(self, range_key: str = "7d") -> dict[str, Any]:
        start = self._range_start(range_key)
        events = self._sales_rag_events_since(start)
        used_session_ids = {event.session_id for event in events if event.used and event.session_id}
        all_sessions = list(self.db.execute(select(ConversationSession)).scalars())
        used_sessions = [session for session in all_sessions if session.session_id in used_session_ids]
        other_sessions = [session for session in all_sessions if session.session_id not in used_session_ids]
        return {
            "range": range_key if range_key in RANGE_OPTIONS else "7d",
            "groups": [
                self._sales_rag_group_metrics("RAG 使用会话", used_sessions, events),
                self._sales_rag_group_metrics("未使用会话", other_sessions, []),
            ],
        }

    def sales_rag_recent_uses(self, limit: int = 10) -> dict[str, Any]:
        statement = (
            select(SalesCaseRAGEvent)
            .where(SalesCaseRAGEvent.hit_count > 0)
            .order_by(SalesCaseRAGEvent.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
        events = list(self.db.execute(statement).scalars())
        return {
            "items": [
                {
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "turn_id": event.turn_id,
                    "hit_count": event.hit_count,
                    "used": event.used,
                    "max_score": round(event.max_score, 4),
                    "avg_score": round(event.avg_score, 4),
                    "reference_ids": _json_loads_list(event.reference_ids_json),
                    "used_reference_ids": _json_loads_list(event.used_reference_ids_json),
                    "created_at": event.created_at.isoformat() if event.created_at else "",
                }
                for event in events
            ],
        }

    def _sop_stage_order(self) -> list[str]:
        rows = list(
            self.db.execute(
                select(KnowledgeSOP).order_by(KnowledgeSOP.created_at, KnowledgeSOP.sop_id)
            ).scalars()
        )
        return _dedupe([row.stage for row in rows if row.stage])

    def _range_start(self, range_key: str) -> datetime:
        range_key = range_key if range_key in RANGE_OPTIONS else "7d"
        return beijing_now() - RANGE_OPTIONS[range_key][0]

    def _sales_rag_events_since(self, start: datetime) -> list[SalesCaseRAGEvent]:
        return list(
            self.db.execute(
                select(SalesCaseRAGEvent).where(SalesCaseRAGEvent.created_at >= start)
            ).scalars()
        )

    def _has_customer_reply_after(self, event: SalesCaseRAGEvent) -> bool:
        if not event.session_id or not event.created_at:
            return False
        return (
            self.db.scalar(
                select(func.count(Message.message_id))
                .where(Message.session_id == event.session_id)
                .where(Message.sender_type == "customer")
                .where(Message.created_at > event.created_at)
            )
            or 0
        ) > 0

    def _sales_rag_group_metrics(
        self,
        label: str,
        sessions: list[ConversationSession],
        events: list[SalesCaseRAGEvent],
    ) -> dict[str, Any]:
        session_ids = {session.session_id for session in sessions}
        high_intent = 0
        if session_ids:
            high_intent = sum(
                1
                for customer in self.db.execute(
                    select(CustomerRecord).where(CustomerRecord.session_id.in_(session_ids))
                ).scalars()
                if customer.purchase_intent == "high"
            )
        continued = sum(1 for event in events if self._has_customer_reply_after(event))
        return {
            "label": label,
            "sessions": len(sessions),
            "avg_message_count": _average(session.message_count for session in sessions),
            "high_intent_rate": _rate(high_intent, len(sessions)),
            "handover_rate": _rate(sum(1 for session in sessions if session.transfer_flag), len(sessions)),
            "continue_reply_rate": _rate(continued, len(events)),
        }

    def _sessions_since(self, start: datetime) -> list[ConversationSession]:
        return list(
            self.db.execute(
                select(ConversationSession).where(ConversationSession.created_at >= start)
            ).scalars()
        )

    def _handover_sessions_since(self, start: datetime) -> list[ConversationSession]:
        return list(
            self.db.execute(
                select(ConversationSession)
                .where(ConversationSession.transfer_flag.is_(True))
                .where(ConversationSession.updated_at >= start)
            ).scalars()
        )

    def _messages_since(self, start: datetime) -> list[Message]:
        return list(self.db.execute(select(Message).where(Message.created_at >= start)).scalars())

    def _turns_since(self, start: datetime) -> list[ConversationTurn]:
        return list(
            self.db.execute(select(ConversationTurn).where(ConversationTurn.created_at >= start)).scalars()
        )

    def _node_invocations_since(self, start: datetime) -> list[NodeInvocation]:
        return list(
            self.db.execute(select(NodeInvocation).where(NodeInvocation.created_at >= start)).scalars()
        )

    def _llm_calls_since(self, start: datetime) -> list[LLMCall]:
        return list(self.db.execute(select(LLMCall).where(LLMCall.created_at >= start)).scalars())

    def _scheduled_tasks_since(self, start: datetime) -> list[ScheduledMessageTask]:
        return list(
            self.db.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.sent_at >= start)
            ).scalars()
        )

    def _followup_jobs_since(self, start: datetime) -> list[ConversationFollowupJob]:
        return list(
            self.db.execute(
                select(ConversationFollowupJob).where(ConversationFollowupJob.sent_at >= start)
            ).scalars()
        )

    def _handover_count_since(self, start: datetime) -> int:
        return int(
            self.db.scalar(
                select(func.count(ConversationSession.session_id))
                .where(ConversationSession.transfer_flag.is_(True))
                .where(ConversationSession.updated_at >= start)
            )
            or 0
        )

    def _high_intent_count(self) -> int:
        return int(
            self.db.scalar(
                select(func.count(CustomerRecord.customer_id)).where(
                    CustomerRecord.purchase_intent == "high"
                )
            )
            or 0
        )

    def _followup_sent_count_since(self, start: datetime) -> int:
        return int(
            self.db.scalar(
                select(func.count(ConversationFollowupJob.job_id))
                .where(ConversationFollowupJob.status == "sent")
                .where(ConversationFollowupJob.sent_at >= start)
            )
            or 0
        )

    def _scheduled_sent_count_since(self, start: datetime) -> int:
        return int(
            self.db.scalar(
                select(func.count(ScheduledMessageTask.task_id))
                .where(ScheduledMessageTask.status == "sent")
                .where(ScheduledMessageTask.sent_at >= start)
            )
            or 0
        )

    def _rag_hits(self, node_runs: list[NodeInvocation]) -> int:
        return sum(
            1
            for run in node_runs
            if run.node_name == "sales_case_rag" and _has_sales_case_references(run.output_json)
        )

    def _safety_triggers(self, node_runs: list[NodeInvocation]) -> int:
        return sum(
            1
            for run in node_runs
            if run.node_name == "safety" and _safety_action(run.output_json) not in {"", "pass"}
        )


def _bucket_labels(start: datetime, end: datetime, bucket: str) -> list[str]:
    labels = []
    current = _floor_time(start, bucket)
    while current <= end:
        labels.append(_bucket_key(current, bucket))
        current += timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    return labels


def _bucket_key(value: datetime, bucket: str) -> str:
    value = _floor_time(value, bucket)
    if bucket == "hour":
        return value.strftime("%Y-%m-%d %H:00")
    return value.strftime("%Y-%m-%d")


def _floor_time(value: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _series(key: str, label: str, buckets: list[str], counter: Counter[str]) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "points": [{"time": bucket, "value": counter.get(bucket, 0)} for bucket in buckets],
    }


def _counter_items(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"label": key or "未知", "value": value} for key, value in counter.items()]


def _rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, 1)


def _average(values) -> int:
    items = [int(value) for value in values if value is not None]
    if not items:
        return 0
    return int(sum(items) / len(items))


def _average_float(values) -> float:
    items = [float(value) for value in values if value is not None]
    if not items:
        return 0.0
    return sum(items) / len(items)


def _json_loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_loads_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _has_sales_case_references(raw: str) -> bool:
    value = _json_loads(raw)
    references = value.get("sales_case_references") or value.get("references")
    return isinstance(references, list) and len(references) > 0


def _safety_action(raw: str) -> str:
    value = _json_loads(raw)
    return str(value.get("action") or value.get("safety_action") or "").strip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
