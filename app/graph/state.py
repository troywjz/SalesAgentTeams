from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from app.agents import AgentRunResult
from app.conversation import CustomerProfile


class SalesGraphState(TypedDict, total=False):
    """LangGraph 销售对话图的全局共享状态。

    每个节点接收当前快照、返回局部更新字典，LangGraph 自动合并回全局状态。
    total=False 表示所有字段均可缺省——节点只需返回自己修改的字段即可。

    会话级字段（原 conversation_state）已拆分到顶层，避免并行节点
    同时修改嵌套对象导致 last-write-wins 冲突。

    数据流向概览::

        message → init → supervisor_router
            → intent → [sop, knowledge, sales_case_rag] → context_gate
            → conversation → vector safety → SafetyAgent
            → final_reply → send → [finalize, memory_update] → END
                                      ↘
                    rewrite_reply → safety    handover → finalize → END

    字段按数据产生顺序排列：
    1. 输入层：message, 会话级字段
    2. 分析层：supervisor, intent, sop, knowledge_output（各 Agent 的输出）
    3. 生成层：draft_reply（ConversationAgent 草稿）
    4. 审核层：safety（SafetyAgent 风控结果）
    5. 输出层：reply（最终回复）、runs（运行记录累加）
    """

    # ── 输入层 ──────────────────────────────────────────────

    message: str
    """用户本次发送的原始消息文本。"""

    # ── 会话级状态（原 conversation_state 拆分到顶层） ──────

    session_id: str
    """会话唯一标识。"""

    turn_id: str
    """对话回合唯一标识，用于关联消息、节点调用、模型调用和异步更新。"""

    customer_id: str
    """客户唯一标识。"""

    current_stage: str
    """当前销售阶段（如 开场、破冰、探需扩需 等）。"""

    customer_profile: CustomerProfile
    """客户画像：姓名、年龄、预算、购买意向等。"""

    history_summary: str
    """历史对话摘要，保留最近 3000 字符作为上下文窗口。"""

    message_count: int
    """当前会话已处理的消息轮次计数。"""

    transfer_flag: bool
    """是否已转人工。置 True 后自动回复链路不再执行。"""

    transfer_reason: str
    """转人工原因。"""

    # ── 知识层（原 knowledge_context 拆分到顶层） ────────────

    knowledge_catalog: list[dict[str, Any]]
    """知识库目录索引。由 init 从 knowledge_list 加载，
    用于让 Agent 知道当前有哪些可查询数据表及其边界。"""

    sop_docs: dict[str, Any]
    """SOP 文档子集，按阶段分组。由 sop/knowledge 节点按需从
    knowledge_sop 读取；未运行相关节点时可为空。"""

    sop_stage_options: list[str]
    """从 knowledge_sop.stage 去重得到的可用销售阶段。
    SOPAgent 只能从该列表中选择 current_stage。"""

    safety_rules: dict[str, Any]
    """风控规则文档。由 safety 节点从 knowledge_safety_rules 读取。
    该字段不提供给 KnowledgeAgent。"""

    skus: list[dict[str, Any]]
    """本轮按需匹配到的商品/SKU 信息。由 knowledge 节点从
    knowledge_skus 读取；简单寒暄或非商品问题时为空。"""

    faq: str
    """本轮按需匹配到的 FAQ 文本片段。由 knowledge 节点从
    knowledge_faq 读取；未查询 FAQ 时为空。"""

    # ── 分析层 ──────────────────────────────────────────────

    supervisor: dict[str, Any]
    """低成本调度器输出。由 supervisor_router 节点写入，
    决定 manual_control / force_handover / direct_reply / full_auto 路径。"""

    intent: dict[str, Any]
    """意图识别结果（IntentAgent 输出）。
    包含 intent_category（high_intent / price_inquiry / general 等）、
    purchase_intent（购买意向度，仅前端展示用）等。"""

    sop: dict[str, Any]
    """SOP 决策结果（SOPAgent 输出）。
    包含当前销售阶段推进建议、是否应转人工（should_transfer）、
    知识检索关键词（knowledge_query）等。"""

    knowledge_output: dict[str, Any]
    """知识检索结果（KnowledgeAgent 输出）。
    包含匹配的 SKU/课程（matched_skus/matched_courses）、
    FAQ 事实（facts）、缺失信息（missing_info）、
    以及 Agent 出错标记（_agent_error）。"""

    knowledge_sufficiency: str | bool | None
    """知识是否充分。未运行 knowledge 节点时为 None。"""

    sales_case_references: list[dict[str, Any]]
    """销售案例 RAG 召回结果。仅提供可借鉴的话术策略和表达方式，
    不作为商品、价格、政策、承诺等事实来源。"""

    safety_retry_count: int
    """本轮已送审的草稿版本计数。
    conversation 生成首版草稿时 +1，rewrite_reply 改写草稿时继续 +1；
    超过上限后转人工，避免风控改写死循环。"""

    # ── 生成层 ──────────────────────────────────────────────

    draft_reply: str
    """ConversationAgent 生成的草稿回复，或 rewrite_reply 改写后的草稿。
    尚未经过风控审查，不代表最终输出。"""

    # ── 审核层 ──────────────────────────────────────────────

    safety: dict[str, Any]
    """风控审查结果（SafetyAgent 输出）。
    核心字段 action：pass（通过）/ revise（需改写）/ block（拦截）/ transfer（转人工）。
    还可能包含 revised_reply（安全审核给出的建议改写稿）、risks（风险列表）等。
    revised_reply 不是直接发送内容，仍需经 rewrite_reply 写回 draft_reply 后再次审核。"""

    # ── 输出层 ──────────────────────────────────────────────

    reply: str
    """最终回复文本。由 final_reply 节点写入，send 节点负责标记已发送。"""

    sent_reply: bool
    """send 节点标记。仅 True 时服务层把 AI 回复视为已发送并写入消息表。"""

    runs: Annotated[list[AgentRunResult], add]
    """所有节点的运行记录累加列表。

    使用 LangGraph 的 Annotated + reducer 机制：
    每个节点返回 ``{"runs": [run]}``，LangGraph 自动调用
    ``operator.add`` 将新记录追加到已有列表，而非覆盖。
    这使得多个节点可以独立写入，最终汇总为完整执行日志。"""
