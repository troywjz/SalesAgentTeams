from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from app.agents import (
    AgentRunResult,
    ConversationAgent,
    IntentAgent,
    KnowledgeAgent,
    MemoryAgent,
    SafetyAgent,
    SOPAgent,
)
from app.conversation import CustomerProfile
from app.conversation import ConversationState
from app.core.config import Settings, get_settings
from app.knowledge import KnowledgeLoader
from app.knowledge.safety_vector import SafetyVectorReviewer
from app.llm import LLMClient
from app.sales_rag import SalesCaseRAGService
from app.graph.supervisor_router import decide_supervisor_route
from app.graph.routing_rules import (
    explicit_knowledge_sufficiency,
    intent_handover_reasons,
    intent_needs_context,
    intent_should_direct_reply,
    intent_should_handover,
    looks_like_knowledge_request,
    safety_retry_exceeded,
)
from app.graph.state import SalesGraphState


class SalesGraphNodes:
    """LangGraph 销售对话图的所有节点实现。

    每个节点方法签名统一为 ``(graph_state) -> partial_update``：
    - 接收当前全局状态快照
    - 返回一个只包含已修改字段的字典，LangGraph 自动合并回全局状态

    会话级字段已拆分到 State 顶层，节点直接读写顶层字段，
    避免并行节点修改嵌套 conversation_state 导致冲突。

    节点执行顺序由 sales_graph.py 中的边定义决定，大致为::

        init → supervisor_router → intent → [sop, knowledge, sales_case_rag]
                                                  ↓ (条件路由)
                              conversation / handover
                                       ↓
                              vector safety → SafetyAgent
                                       ↓ (条件路由)
                              final_reply / rewrite_reply / handover
                                       ↓
                              send → [finalize, memory_update]
                                       ↓
                                      END
    """

    def __init__(
        self,
        llm_client: LLMClient,
        knowledge_loader: KnowledgeLoader | None = None,
        safety_vector_reviewer: SafetyVectorReviewer | None = None,
        sales_case_rag_service: SalesCaseRAGService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.knowledge_loader = knowledge_loader or KnowledgeLoader()
        self.safety_vector_reviewer = (
            safety_vector_reviewer
            if safety_vector_reviewer is not None
            else SafetyVectorReviewer(settings=self.settings)
        )
        self.sales_case_rag_service = (
            sales_case_rag_service
            if sales_case_rag_service is not None
            else SalesCaseRAGService(settings=self.settings)
        )
        load_identity = getattr(self.knowledge_loader, "load_business_identity", None)
        business_identity = load_identity() if callable(load_identity) else None
        agent_kwargs = {"business_identity": business_identity}
        self.intent_agent = IntentAgent(llm_client, **agent_kwargs)
        self.memory_agent = MemoryAgent(llm_client, **agent_kwargs)
        self.sop_agent = SOPAgent(llm_client, **agent_kwargs)
        self.knowledge_agent = KnowledgeAgent(llm_client, **agent_kwargs)
        self.conversation_agent = ConversationAgent(llm_client, **agent_kwargs)
        self.safety_agent = SafetyAgent(llm_client, **agent_kwargs)

    # ── 入口与调度节点 ───────────────────────────────────────

    async def init(self, graph_state: SalesGraphState) -> SalesGraphState:
        """初始化回合状态并加载知识库上下文。

        不调用 LLM，只读取知识库目录和风控规则。
        SKU/FAQ/SOP 明细由后续节点按需读取，避免每轮把全部知识塞进上下文。
        """
        ctx = self.knowledge_loader.load_context()
        return {
            "sop_docs": ctx.get("sales_sop", {}),
            "sop_stage_options": self.knowledge_loader.list_sop_stages(include_terminal=False),
            "safety_rules": ctx.get("safety_rules", {}),
            "skus": ctx.get("skus", []),
            "faq": ctx.get("faq", ""),
            "knowledge_catalog": ctx.get("knowledge_catalog", []),
            "intent": graph_state.get("intent"),
            "sop": graph_state.get("sop"),
            "knowledge_output": graph_state.get("knowledge_output"),
            "knowledge_sufficiency": graph_state.get("knowledge_sufficiency"),
            "sales_case_references": graph_state.get("sales_case_references", []),
            "safety": graph_state.get("safety"),
            "safety_retry_count": graph_state.get("safety_retry_count", 0),
            "draft_reply": graph_state.get("draft_reply"),
            "reply": graph_state.get("reply", ""),
            "sent_reply": False,
            "runs": graph_state.get("runs", []),
        }

    async def supervisor_router(self, graph_state: SalesGraphState) -> SalesGraphState:
        """低成本调度节点：基于规则决定本轮走完整链路还是轻量链路。"""
        state = _conversation_state_from_graph(graph_state)
        decision = decide_supervisor_route(_require_message(graph_state), state)
        supervisor = decision.model_dump()
        route = supervisor.get("route")
        if route == "force_handover":
            reason = "; ".join(supervisor.get("reasons") or []) or "触发强制转人工规则"
            return {
                "supervisor": supervisor,
                "transfer_reason": reason,
            }
        return {"supervisor": supervisor}

    # ── 分析层节点 ───────────────────────────────────────────

    async def intent(self, graph_state: SalesGraphState) -> SalesGraphState:
        """意图识别节点：判断用户消息的意图类别和购买意向度。

        输入：用户消息 + 历史摘要 + 当前销售阶段
        输出：intent 字典（含 intent_category、purchase_intent 等字段）
        """
        message = _require_message(graph_state)
        run = await self.intent_agent.run(
            {
                "message": message,
                "history_summary": graph_state.get("history_summary", ""),
                "current_stage": graph_state.get("current_stage", "开场"),
                "knowledge_catalog": graph_state.get("knowledge_catalog", []),
                "customer_profile": (
                    graph_state.get("customer_profile") or CustomerProfile()
                ).model_dump(),
            }
        )
        intent = _as_dict(run.output)
        return {"intent": intent, "runs": [run]}

    async def sop(self, graph_state: SalesGraphState) -> SalesGraphState:
        """SOP 决策节点：根据意图和画像决定销售阶段推进策略。

        输入：用户消息 + 意图 + 画像 + 当前阶段 + SOP 文档
        输出：sop 字典（含 should_transfer / knowledge_query / current_stage 等）
        副作用：若 SOP 建议推进阶段，同步更新 current_stage 顶层字段。
        """
        message = _require_message(graph_state)
        current_profile = graph_state.get("customer_profile") or CustomerProfile()
        sop_docs = graph_state.get("sop_docs", {})
        sop_stage_options = graph_state.get("sop_stage_options") or []
        if hasattr(self.knowledge_loader, "query_sop_docs"):
            sop_docs = self.knowledge_loader.query_sop_docs(
                message=message,
                current_stage=graph_state.get("current_stage", "开场"),
            )
        if not sop_stage_options and hasattr(self.knowledge_loader, "list_sop_stages"):
            sop_stage_options = self.knowledge_loader.list_sop_stages(include_terminal=False)
        run = await self.sop_agent.run(
            {
                "message": message,
                "intent": graph_state.get("intent", {}),
                "customer_profile": current_profile.model_dump(),
                "current_stage": graph_state.get("current_stage", "开场"),
                "stage_options": sop_stage_options,
                "history_summary": graph_state.get("history_summary", ""),
                "sales_sop": sop_docs,
            }
        )
        sop = _as_dict(run.output)
        normalized_stage = _normalize_sop_stage(
            sop.get("current_stage"),
            current_stage=graph_state.get("current_stage", "开场"),
            stage_options=sop_stage_options,
        )
        if normalized_stage:
            sop["current_stage"] = normalized_stage
        updates: SalesGraphState = {
            "sop": sop,
            "sop_docs": sop_docs,
            "sop_stage_options": sop_stage_options,
            "runs": [run],
        }
        if normalized_stage:
            updates["current_stage"] = normalized_stage
        return updates

    async def knowledge(self, graph_state: SalesGraphState) -> SalesGraphState:
        """知识检索节点：根据用户问题从知识库中检索相关信息。

        输入：用户消息 + 当前阶段 + SKU/FAQ/SOP 上下文
        输出：knowledge_output 字典和 knowledge_sufficiency

        此节点是知识链路的最后一步，后续通过条件路由决定走向：
        - 信息充足 → conversation（生成回复）
        - 信息不足 / 检索出错 → handover（转人工）
        """
        message = _require_message(graph_state)
        knowledge_context = {
            "selected_knowledge_sources": [],
            "skus": graph_state.get("skus", []),
            "faq": graph_state.get("faq", ""),
            "sop_docs": graph_state.get("sop_docs", {}),
        }
        if hasattr(self.knowledge_loader, "query_context"):
            knowledge_context = self.knowledge_loader.query_context(
                message=message,
                intent=graph_state.get("intent", {}),
                current_stage=graph_state.get("current_stage", "开场"),
            )
        run = await self.knowledge_agent.run(
            {
                "message": message,
                "intent": graph_state.get("intent", {}),
                "current_stage": graph_state.get("current_stage", "开场"),
                "knowledge_catalog": graph_state.get("knowledge_catalog", []),
                "selected_knowledge_sources": knowledge_context.get("selected_knowledge_sources", []),
                "skus": knowledge_context.get("skus", []),
                "faq": knowledge_context.get("faq", ""),
                "sop_docs": knowledge_context.get("sop_docs", {}),
            }
        )
        knowledge_output = _as_dict(run.output)
        return {
            "skus": knowledge_context.get("skus", []),
            "faq": knowledge_context.get("faq", ""),
            "knowledge_output": knowledge_output,
            "knowledge_sufficiency": _knowledge_sufficiency(knowledge_output),
            "runs": [run],
        }

    async def context_gate(self, graph_state: SalesGraphState) -> SalesGraphState:
        """fan-in 汇聚节点：等待按需执行的 SOP/knowledge/RAG 节点完成。

        该节点不调用模型，只作为 LangGraph 条件路由的源节点。
        """
        return {}

    async def sales_case_rag(self, graph_state: SalesGraphState) -> SalesGraphState:
        """销售案例 RAG 节点：召回少量优秀销售话术供回复生成参考。

        该节点只提供表达策略示例，不替代知识库事实、SOP 阶段和风控规则。
        """
        message = _require_message(graph_state)
        current_stage = graph_state.get("current_stage", "开场")
        intent = graph_state.get("intent", {})
        started = time.perf_counter()
        references = await self.sales_case_rag_service.retrieve(
            message=message,
            current_stage=current_stage,
            intent=intent,
        )
        prompt_references = [
            reference.to_prompt_dict()
            for reference in references[: max(1, self.settings.sales_rag_max_references)]
        ]
        max_chars = max(200, self.settings.sales_rag_max_reference_chars)
        trimmed: list[dict[str, Any]] = []
        used_chars = 0
        for reference in prompt_references:
            serialized = str(reference)
            if used_chars + len(serialized) > max_chars:
                break
            trimmed.append(reference)
            used_chars += len(serialized)
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        run = AgentRunResult(
            agent_name="sales_case_rag",
            output={"sales_case_references": trimmed},
            raw_output=str(trimmed),
            input_payload={
                "message": message,
                "current_stage": current_stage,
                "intent": intent,
            },
            elapsed_ms=elapsed_ms,
            provider="local",
            model="sales-case-rag",
        )
        return {"sales_case_references": trimmed, "runs": [run]}

    # ── 回复生成与审核节点 ────────────────────────────────────

    async def conversation(self, graph_state: SalesGraphState) -> SalesGraphState:
        """回复生成节点：综合所有分析结果生成草稿回复。

        输入：用户消息 + 意图 + SOP 决策 + 知识检索 + 画像 + 历史摘要
        输出：draft_reply（未经风控审查的草稿）和 safety_retry_count

        提取回复文本时按优先级依次尝试：
        final_reply → value → raw_output（兜底取 LLM 原始输出）
        """
        current_profile = graph_state.get("customer_profile") or CustomerProfile()
        run = await self.conversation_agent.run(
            {
                "message": _require_message(graph_state),
                "intent": graph_state.get("intent", {}),
                "sop_decision": graph_state.get("sop", {}),
                "knowledge": graph_state.get("knowledge_output", {}),
                "sales_case_references": graph_state.get("sales_case_references", []),
                "customer_profile": current_profile.model_dump(),
                "history_summary": graph_state.get("history_summary", ""),
            }
        )
        conv_output = _as_dict(run.output)
        draft_reply = str(conv_output.get("final_reply") or conv_output.get("value") or "")
        if not draft_reply and isinstance(run.output, dict):
            draft_reply = str(run.output.get("raw_output", "")).strip()
        retry_count = graph_state.get("safety_retry_count", 0) + 1
        updates: SalesGraphState = {
            "draft_reply": draft_reply,
            "safety_retry_count": retry_count,
            "runs": [run],
        }
        sop_stage = str((graph_state.get("sop") or {}).get("current_stage") or "").strip()
        if sop_stage:
            updates["current_stage"] = sop_stage
        return updates

    async def safety(self, graph_state: SalesGraphState) -> SalesGraphState:
        """风控审核节点：对草稿回复进行合规性和风险检查。

        输入：用户消息 + 草稿回复 + 意图 + SOP + 画像 + 风控规则
        输出：safety 字典，核心字段 action：
          - pass：通过，草稿可直接使用
          - revise：需改写（可含 revised_reply 建议稿，用于减少二次生成）
          - block：拦截，不允许发送
          - transfer：建议转人工处理
        """
        current_profile = graph_state.get("customer_profile") or CustomerProfile()
        safety_rules = graph_state.get("safety_rules", {})
        if hasattr(self.knowledge_loader, "load_safety_rules"):
            safety_rules = self.knowledge_loader.load_safety_rules()

        # 向量审核是 SafetyAgent 前的可选增强层。没有向量数据时，
        # SafetyVectorReviewer 会直接返回 pass，主链路仍只调用 SafetyAgent。
        vector_review: dict[str, Any] | None = None
        if self.settings.safety_vector_enabled:
            try:
                vector_review = await self.safety_vector_reviewer.review(
                    draft_reply=graph_state.get("draft_reply", ""),
                    session_id=graph_state.get("session_id", ""),
                    turn_id=graph_state.get("turn_id", ""),
                    node_name="safety",
                )
                if vector_review.get("action") == "revise":
                    return {
                        "safety_rules": safety_rules,
                        "safety": {
                            "action": "revise",
                            "source": "vector",
                            "risks": vector_review.get("risks", []),
                            "matches": vector_review.get("matches", []),
                            "vector_review": vector_review,
                        },
                    }
            except Exception as exc:
                # 向量服务或审计表异常不能让主安全审核失效，继续使用 SafetyAgent。
                vector_review = {
                    "enabled": True,
                    "source_available": True,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }

        run = await self.safety_agent.run(
            {
                "message": _require_message(graph_state),
                "draft_reply": graph_state.get("draft_reply", ""),
                "intent": graph_state.get("intent", {}),
                "sop_decision": graph_state.get("sop", {}),
                "customer_profile": current_profile.model_dump(),
                "current_stage": graph_state.get("current_stage", "开场"),
                "safety_rules": safety_rules,
            }
        )
        safety = _as_dict(run.output)
        if vector_review:
            safety["vector_review"] = vector_review
        return {"safety_rules": safety_rules, "safety": safety, "runs": [run]}

    # ── 分支节点（条件路由后的目标节点） ──────────────────────

    async def ask_clarification(self, graph_state: SalesGraphState) -> SalesGraphState:
        """追问节点：知识不足时向用户追问补充信息。

        不调用 LLM，使用模板直接生成追问话术。
        优先引用 knowledge.missing_info 中的具体缺失项，
        若缺失项为空则使用通用追问模板。
        """
        knowledge = graph_state.get("knowledge", {})
        missing_items = knowledge.get("missing_info") or []
        missing_text = "、".join(str(item) for item in missing_items[:2])
        if missing_text:
            reply = f"这部分信息我先帮你确认一下。为了避免说错，能再补充一下你主要想了解的是{missing_text}里的哪一项吗？"
        else:
            reply = "这部分信息我先帮你确认一下。你方便再补充一下具体想了解的商品、预算或使用场景吗？"
        return {"reply": reply}

    async def rewrite_reply(self, graph_state: SalesGraphState) -> SalesGraphState:
        """改写节点：风控不通过时，基于风险原因重新生成安全回复。

        改写后的回复写入 draft_reply（而非 reply），随后流转回 safety 节点
        重新审核，确保改写结果也通过风控。

        优先使用 SafetyAgent 已提供的 revised_reply（避免二次 LLM 调用），
        仅在 SafetyAgent 未提供改写结果时，才调用 ConversationAgent 重新生成。
        """
        safety = graph_state.get("safety", {})
        retry_count = graph_state.get("safety_retry_count", 0) + 1
        revised_reply = str(safety.get("revised_reply") or "").strip()
        if revised_reply:
            return {"draft_reply": revised_reply, "safety_retry_count": retry_count}

        current_profile = graph_state.get("customer_profile") or CustomerProfile()
        run = await self.conversation_agent.run(
            {
                "message": _require_message(graph_state),
                "intent": graph_state.get("intent", {}),
                "sop_decision": graph_state.get("sop", {}),
                "knowledge": graph_state.get("knowledge_output", {}),
                "sales_case_references": graph_state.get("sales_case_references", []),
                "customer_profile": current_profile.model_dump(),
                "history_summary": graph_state.get("history_summary", ""),
                "rewrite_required": True,
                "rewrite_reason": safety.get("risks", []),
                "unsafe_draft_reply": graph_state.get("draft_reply", ""),
            }
        )
        conv_output = _as_dict(run.output)
        draft_reply = str(conv_output.get("final_reply") or conv_output.get("value") or "")
        if not draft_reply and isinstance(run.output, dict):
            draft_reply = str(run.output.get("raw_output", "")).strip()
        return {"draft_reply": draft_reply, "safety_retry_count": retry_count, "runs": [run]}

    async def handover(self, graph_state: SalesGraphState) -> SalesGraphState:
        """转人工节点：标记会话转交人工处理，不发送 AI 回复。

        触发场景：
        1. SOP 判定应转人工（should_transfer=True）
        2. 风控判定需转人工（action=transfer）
        3. 知识检索不足，无法自动回复

        副作用：设置 transfer_flag=True，保留原销售阶段。
        转人工状态由 transfer_flag 单独表达，不作为销售阶段写入 current_stage。
        """
        safety = graph_state.get("safety") or {}
        sop = graph_state.get("sop") or {}
        knowledge = graph_state.get("knowledge_output") or {}
        supervisor = graph_state.get("supervisor") or {}
        intent = graph_state.get("intent") or {}
        transfer_reason = str(
            safety.get("transfer_reason")
            or (sop.get("reason") if bool(sop.get("should_transfer")) else "")
            or _knowledge_transfer_reason(knowledge)
            or _intent_transfer_reason(
                intent,
                message=graph_state.get("message", ""),
                profile=graph_state.get("customer_profile"),
            )
            or graph_state.get("transfer_reason")
            or "; ".join(supervisor.get("reasons") or [])
            or "需要人工跟进"
        )
        return {
            "transfer_flag": True,
            "transfer_reason": transfer_reason,
            "reply": "",
            "sent_reply": False,
        }

    async def final_reply(self, graph_state: SalesGraphState) -> SalesGraphState:
        """最终回复节点：根据风控结果选择输出文本。

        - block：使用安全兜底回复（safe_reply 或默认文案）
        - pass/其他：优先使用风控审核通过的回复（approved_reply），
          其次使用改写回复（revised_reply），最后回退到草稿（draft_reply）
        """
        safety = graph_state.get("safety", {})
        action = str(safety.get("action", "pass")).lower()
        if action == "block":
            reply = str(
                safety.get("safe_reply")
                or "这个问题我先帮你记录下来，稍后让老师进一步确认后回复你。"
            )
        else:
            reply = str(
                safety.get("approved_reply")
                or safety.get("revised_reply")
                or graph_state.get("draft_reply")
                or ""
            )
        return {"reply": reply}

    async def send(self, graph_state: SalesGraphState) -> SalesGraphState:
        """发送节点：标记最终回复已进入客户可见输出链路。

        本地 Demo 的真实写消息动作在服务层完成；该节点用于保证拓扑语义：
        只有通过 send 的回复才会被当作已发送消息保存。
        """
        reply = str(graph_state.get("reply") or "").strip()
        return {"sent_reply": bool(reply)}

    # ── 收尾节点 ─────────────────────────────────────────────

    async def finalize(self, graph_state: SalesGraphState) -> SalesGraphState:
        """同步收尾节点：只更新会话事实，不调用 LLM。

        职责：
        1. 递增消息计数
        2. 保留转人工状态和原因
        3. 不写画像、不写压缩记忆，避免与 memory_update 抢同一职责
        """
        reply = str(graph_state.get("reply") or "").strip()
        message_count = graph_state.get("message_count", 0) + 1
        return {
            "message_count": message_count,
            "reply": reply,
        }

    async def memory_update(self, graph_state: SalesGraphState) -> SalesGraphState:
        """异步语义的记忆更新节点：调用 LLM 压缩长期记忆并更新画像。

        读取旧压缩记忆和本轮客户/AI 对话，写入新的 history_summary
        与 customer_profile。实际持久化写入 conversation_memories 表。
        """
        reply = str(graph_state.get("reply") or "").strip()
        if not reply:
            return {}

        current_profile = graph_state.get("customer_profile") or CustomerProfile()
        run = await self.memory_agent.run(
            {
                "current_memory": graph_state.get("history_summary", ""),
                "new_exchange": {
                    "customer": _require_message(graph_state),
                    "salesagent": reply,
                },
                "message": _require_message(graph_state),
                "reply": reply,
                "intent": graph_state.get("intent", {}),
                "sop": graph_state.get("sop", {}),
                "knowledge": graph_state.get("knowledge_output", {}),
                "safety": graph_state.get("safety", {}),
                "current_profile": current_profile.model_dump(),
                "current_stage": graph_state.get("current_stage", "开场"),
            }
        )
        output = _as_dict(run.output)
        updated_profile = _apply_profile_update(current_profile, output)
        memory_summary = _extract_memory_summary(
            output,
            old_summary=graph_state.get("history_summary", ""),
            message=_require_message(graph_state),
            reply=reply,
        )
        return {
            "customer_profile": updated_profile,
            "history_summary": memory_summary,
            "runs": [run],
        }


# ── 条件路由函数 ──────────────────────────────────────────────


def route_after_supervisor(graph_state: SalesGraphState) -> str:
    """调度器后的条件路由。"""
    route = str((graph_state.get("supervisor") or {}).get("route") or "full_auto")
    if route in {"manual_control", "force_handover"}:
        return "handover"
    if route == "direct_reply":
        return "conversation"
    return "intent"


def route_after_intent(graph_state: SalesGraphState) -> str | list[str]:
    """意图识别后的按需扇出路由。

    返回多个目标时，LangGraph 会并行执行对应节点；返回单个目标时直接走
    轻量链路或转人工链路。
    """
    intent = graph_state.get("intent") or {}
    message = str(graph_state.get("message") or "")

    if intent_should_handover(
        intent,
        message=message,
        profile=graph_state.get("customer_profile"),
    ):
        return "handover"
    if intent_should_direct_reply(intent):
        return "conversation"

    targets: list[str] = []
    needs_context = intent_needs_context(intent)
    if needs_context or looks_like_knowledge_request(message):
        targets.append("knowledge")
    if needs_context or targets:
        targets.append("sop")
        targets.append("sales_case_rag")
    return targets or "conversation"


def route_after_knowledge(graph_state: SalesGraphState) -> str:
    """上下文汇聚后的条件路由：决定是继续生成回复还是转人工。

    决策逻辑（按优先级）：
    1. SOP 建议转人工 → handover
    2. 知识检索出错 → handover（不能给客户错误信息）
    3. 已运行知识检索但完全没有可用事实 → handover
    4. 知识充足或有部分可用事实 → conversation（谨慎生成回复）
    """
    sop = graph_state.get("sop") or {}
    if bool(sop.get("should_transfer")):
        return "handover"

    knowledge = graph_state.get("knowledge_output")
    if knowledge is None:
        return "conversation"

    if knowledge.get("_agent_error"):
        return "handover"

    if _knowledge_sufficiency(knowledge) is False and not _has_usable_knowledge(knowledge):
        return "handover"

    return "conversation"


def route_after_safety(graph_state: SalesGraphState) -> str:
    """风控节点之后的条件路由：决定是直接输出、改写、还是转人工。

    映射关系：
    - action=transfer → "handover"（转人工）
    - action=revise   → "rewrite"（改写回复，对应 rewrite_reply 节点，
                        改写后回到 safety 重新审核）
    - action=pass/block → "final_reply"（最终输出节点内部再区分通过/拦截）
    """
    if safety_retry_exceeded(graph_state.get("safety_retry_count", 0)):
        return "handover"

    action = str((graph_state.get("safety") or {}).get("action", "pass")).lower()
    if action == "transfer":
        return "handover"
    if action == "revise":
        return "rewrite"
    return "final_reply"


# ── 辅助函数 ──────────────────────────────────────────────────


def _normalize_sop_stage(
    value: Any,
    *,
    current_stage: str,
    stage_options: list[str],
) -> str:
    """将 SOPAgent 返回阶段约束到 knowledge_sop.stage 去重列表内。"""
    requested = str(value or "").strip()
    current = str(current_stage or "").strip()
    valid_stages = [str(stage).strip() for stage in stage_options if str(stage).strip()]
    if requested in valid_stages:
        return requested
    if requested in {"handover", "closed", "转人工", "已结束", "结束"}:
        return current
    if not valid_stages:
        return requested
    if current in valid_stages:
        return current
    return ""


def serialize_run(
    run: AgentRunResult,
    *,
    include_llm_call_details: bool = False,
) -> dict[str, Any]:
    """将 Agent 运行记录序列化为字典，用于日志和 API 响应。"""
    data = asdict(run)
    if include_llm_call_details:
        return data
    # API 只返回 LLM 尝试摘要；完整请求/响应已写入 llm_calls 表，避免流式事件过大。
    data["llm_call_attempts"] = [
        {
            "provider": call.provider,
            "model": call.model,
            "attempt_index": call.attempt_index,
            "elapsed_ms": call.elapsed_ms,
            "success": call.success,
            "error_type": call.error_type,
            "error_message": call.error_message,
        }
        for call in run.llm_call_attempts
    ]
    return data


def _conversation_state_from_graph(graph_state: SalesGraphState) -> ConversationState:
    return ConversationState(
        session_id=graph_state.get("session_id", ""),
        customer_id=graph_state.get("customer_id", ""),
        current_stage=graph_state.get("current_stage", "开场"),
        customer_profile=graph_state.get("customer_profile") or CustomerProfile(),
        history_summary=graph_state.get("history_summary", ""),
        message_count=graph_state.get("message_count", 0),
        transfer_flag=graph_state.get("transfer_flag", False),
        transfer_reason=graph_state.get("transfer_reason", ""),
    )


def _apply_profile_update(
    current_profile: CustomerProfile,
    output: dict[str, Any],
) -> CustomerProfile:
    """将 MemoryAgent 输出中的画像信息增量合并到当前客户画像。

    合并规则：
    - 只更新 CustomerProfile 中已定义的字段（忽略未知字段）
    - 空值（None / "" / []）不覆盖已有值（防止信息丢失）
    - 非 dict 输出直接忽略（容错处理）
    """
    incoming = output.get("customer_profile") or output.get("profile") or {}
    if not isinstance(incoming, dict):
        return current_profile

    updated = current_profile.model_dump()
    for key, value in incoming.items():
        if key not in updated:
            continue
        if value in (None, "", []):
            continue
        updated[key] = value
    return CustomerProfile.model_validate(updated)


def _extract_memory_summary(
    output: dict[str, Any],
    *,
    old_summary: str,
    message: str,
    reply: str,
) -> str:
    """从 MemoryAgent 输出中提取新的压缩记忆。

    兼容字段：history_summary / memory / summary / session.memory。
    如果模型暂未按新格式输出，则使用确定性追加作为兜底，避免记忆中断。
    """
    session_obj = output.get("session") if isinstance(output.get("session"), dict) else {}
    value = (
        output.get("history_summary")
        or output.get("memory")
        or output.get("summary")
        or session_obj.get("memory")
    )
    if isinstance(value, str) and value.strip():
        return value.strip()[-3000:]
    return f"{old_summary}\n客户：{message}\nAI：{reply}\n"[-3000:]


def _knowledge_sufficiency(knowledge: dict[str, Any]) -> bool | str:
    explicit = explicit_knowledge_sufficiency(knowledge.get("knowledge_sufficiency"))
    if explicit is not None:
        return explicit

    missing_items = knowledge.get("missing_info") or []
    facts = knowledge.get("facts") or []
    matched_skus = knowledge.get("matched_skus") or knowledge.get("matched_courses") or []
    if missing_items and not facts and not matched_skus:
        return False
    return True


def _has_usable_knowledge(knowledge: dict[str, Any]) -> bool:
    """判断知识检索是否仍有可用于生成回复的事实。"""
    facts = knowledge.get("facts") or []
    matched_skus = knowledge.get("matched_skus") or knowledge.get("matched_courses") or []
    policy_notes = knowledge.get("policy_notes") or []
    return bool(facts or matched_skus or policy_notes)


def _knowledge_transfer_reason(knowledge: dict[str, Any]) -> str:
    """生成知识不足导致转人工的可读原因。"""
    if not knowledge:
        return ""
    if knowledge.get("_agent_error"):
        return "知识检索失败，需要人工确认后回复"
    if _knowledge_sufficiency(knowledge) is not False:
        return ""
    missing_items = knowledge.get("missing_info") or []
    if missing_items:
        return "知识库信息不足：" + "、".join(str(item) for item in missing_items[:3])
    return "知识库信息不足，需要人工确认后回复"


def _intent_transfer_reason(
    intent: dict[str, Any],
    *,
    message: str = "",
    profile: Any = None,
) -> str:
    """生成意图识别触发转人工的可读原因。"""
    reasons = intent_handover_reasons(intent, message=message, profile=profile)
    if not reasons:
        return ""
    return "意图识别触发转人工：" + "、".join(reasons)


def _require_message(graph_state: SalesGraphState) -> str:
    """从图状态中提取用户消息，缺失时抛出异常。

    message 是每次图调用的必需输入，缺失通常意味着 API 层传参错误。
    """
    message = graph_state.get("message")
    if not message:
        raise ValueError("SalesGraphState is missing message.")
    return message


def _as_dict(value: dict[str, Any] | str) -> dict[str, Any]:
    """将 Agent 输出统一转为字典格式。

    Agent 的 run.output 通常为 dict，但 LLM 有时返回纯字符串。
    此函数将字符串包装为 {"value": str}，保证下游代码统一按 dict 处理。
    """
    if isinstance(value, dict):
        return value
    return {"value": value}
