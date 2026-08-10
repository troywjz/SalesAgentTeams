from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import beijing_now
from app.db.base import Base


def utc_now() -> datetime:
    return beijing_now()


class ConversationSession(Base):
    """会话主表：每个对话 session 一行，只保存回合事实和路由状态。

    压缩记忆已拆到 conversation_memories，避免 finalize 与 memory_update
    在同一张表里并发写入不同语义的数据。
    """
    __tablename__ = "conversation_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    sales_id: Mapped[str] = mapped_column(String(64), index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    current_stage: Mapped[str] = mapped_column(String(64), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    transfer_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_reason: Mapped[str] = mapped_column(Text, default="")
    history_summary: Mapped[str] = mapped_column(Text, default="")
    latest_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class ConversationSOPState(Base):
    """Per-session SOP runtime state."""
    __tablename__ = "conversation_sop_states"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    current_stage: Mapped[str] = mapped_column(String(128), default="", index=True)
    followup_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    last_customer_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sales_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    latest_job_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    updated_by_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class ConversationFollowupJob(Base):
    """SOP timeout follow-up job."""
    __tablename__ = "conversation_followup_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    stage: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    trigger_reason: Mapped[str] = mapped_column(String(128), default="timeout", index=True)
    reference_script: Mapped[str] = mapped_column(Text, default="")
    timeout_action: Mapped[str] = mapped_column(String(64), default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    cancelled_reason: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledMessageTask(Base):
    """Manual scheduled outbound message task."""
    __tablename__ = "scheduled_message_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_mode: Mapped[str] = mapped_column(String(32), default="all", index=True)
    target_stage: Mapped[str] = mapped_column(String(128), default="", index=True)
    selected_session_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    message_text: Mapped[str] = mapped_column(Text, default="")
    sent_session_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by_sales_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_by_sales_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMemory(Base):
    """会话压缩记忆：由 memory_update 节点单独维护。"""
    __tablename__ = "conversation_memories"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    sales_id: Mapped[str] = mapped_column(String(64), index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    memory_summary: Mapped[str] = mapped_column(Text, default="")
    last_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class CustomerRecord(Base):
    """客户列表：当前阶段每个会话对应一个客户。"""
    __tablename__ = "list_customer"

    customer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    age: Mapped[str] = mapped_column(String(64), default="")
    education: Mapped[str] = mapped_column(String(128), default="")
    work_status: Mapped[str] = mapped_column(String(128), default="")
    learning_goal: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[str] = mapped_column(String(128), default="")
    urgency: Mapped[str] = mapped_column(String(128), default="")
    concerns_json: Mapped[str] = mapped_column(Text, default="[]")
    purchase_intent: Mapped[str] = mapped_column(String(32), default="low", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class SalesUser(Base):
    """销售用户列表：记录销售身份、团队和权限。"""
    __tablename__ = "list_sales"

    sales_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team: Mapped[str] = mapped_column(String(128), default="", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(255), default="", unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(64), default="sales", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class ConversationTurn(Base):
    """对话回合主表：把多条消息、节点调用和模型调用串成一次处理回合。"""
    __tablename__ = "conversation_turns"

    turn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    turn_index: Mapped[int] = mapped_column(Integer, default=1, index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(64), default="queued", index=True)
    input_message_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    client_message_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    input_text: Mapped[str] = mapped_column(Text, default="")
    reply_text: Mapped[str] = mapped_column(Text, default="")
    parent_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    superseded_by_turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class Message(Base):
    __tablename__ = "conversation_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sales_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), index=True)
    sender_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NodeInvocation(Base):
    """节点调用记录：以node为单位记录LLM调用。"""
    __tablename__ = "graph_node_invocations"

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_name: Mapped[str] = mapped_column(String(64), index=True)
    model_provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128))
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    success: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str] = mapped_column(Text, default="")
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text)
    raw_output: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LLMCall(Base):
    """LLM供应商调用记录：以每一次 provider/model 尝试为单位记录 fallback 链路。"""
    __tablename__ = "llm_calls"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_invocation_id: Mapped[str] = mapped_column(String(64), index=True)
    node_name: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    api_url: Mapped[str] = mapped_column(Text, default="")
    protocol: Mapped[str] = mapped_column(String(64), default="")
    attempt_index: Mapped[int] = mapped_column(Integer, default=1)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=1, index=True)
    error_type: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    usage_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConversationReadCursor(Base):
    __tablename__ = "conversation_read_cursors"

    cursor_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    viewer_type: Mapped[str] = mapped_column(String(32), index=True)
    last_read_message_id: Mapped[str] = mapped_column(String(64), default="")
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class KnowledgeList(Base):
    """知识库目录表：描述有哪些知识表、适合什么时候查询。"""
    __tablename__ = "knowledge_list"

    knowledge_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    use_when: Mapped[str] = mapped_column(Text, default="")
    do_not_use_when: Mapped[str] = mapped_column(Text, default="")
    query_hints_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class KnowledgeSKU(Base):
    """SKU 知识表：商品、课程、服务统一进入这里，价格统一按元存储。"""
    __tablename__ = "knowledge_skus"

    sku_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sku_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    sku_alias: Mapped[str] = mapped_column(Text, default="")
    sku_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(64), default="", index=True)
    target_users_json: Mapped[str] = mapped_column(Text, default="[]")
    learning_goals_json: Mapped[str] = mapped_column(Text, default="[]")
    selling_points_json: Mapped[str] = mapped_column(Text, default="[]")
    delivery: Mapped[str] = mapped_column(Text, default="")
    list_price_yuan: Mapped[str] = mapped_column(String(64), default="")
    deal_price_yuan: Mapped[str] = mapped_column(String(64), default="")
    currency: Mapped[str] = mapped_column(String(32), default="CNY")
    discount_policy: Mapped[str] = mapped_column(Text, default="")
    policy_notes: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class KnowledgeSOP(Base):
    """SOP knowledge table, aligned with data/knowledge/sop.csv."""
    __tablename__ = "knowledge_sop"

    sop_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    stage: Mapped[str] = mapped_column(String(128), default="", index=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    reference_script: Mapped[str] = mapped_column(Text, default="")
    handover_criteria: Mapped[str] = mapped_column(Text, default="")
    wait_minutes: Mapped[int] = mapped_column(Integer, default=0)
    timeout_action: Mapped[str] = mapped_column(String(64), default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

class KnowledgeFAQ(Base):
    """FAQ 知识表：高频问答、政策说明和业务说明。"""
    __tablename__ = "knowledge_faq"

    faq_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    source_section: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class KnowledgeSafetyRule(Base):
    """风控知识表：字段严格对应《销售话术管理规定》表格列。"""
    __tablename__ = "knowledge_safety_rules"

    rule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    level: Mapped[str] = mapped_column(Text, default="")
    primary_category: Mapped[str] = mapped_column(Text, default="")
    secondary_category: Mapped[str] = mapped_column(Text, default="")
    standard: Mapped[str] = mapped_column(Text, default="")
    violation: Mapped[str] = mapped_column(Text, default="")
    handling_result: Mapped[str] = mapped_column(Text, default="")
    # Windows Demo 使用文本形式保存向量，兼容未安装 pgvector 扩展的本地环境；
    # 向量审核只在这些列存在实际数据时启用。
    violation_embedding_gjld_q3e8b: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    violation_embedding_albl_tev4: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class SalesRAGConversation(Base):
    """销售案例 RAG 会话：保存从外部聊天表格导入的会话级元数据。"""
    __tablename__ = "sales_rag_conversations"

    conversation_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    source_path: Mapped[str] = mapped_column(Text, default="")
    source_sheet: Mapped[str] = mapped_column(String(128), default="")
    raw_conversation_id: Mapped[str] = mapped_column(String(128), default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    text_message_count: Mapped[int] = mapped_column(Integer, default=0)
    usable_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class SalesRAGChunk(Base):
    """销售案例 RAG 片段：用于检索的客户问题、销售回复和少量上下文。"""
    __tablename__ = "sales_rag_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_hash: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    customer_text: Mapped[str] = mapped_column(Text, default="")
    sales_reply: Mapped[str] = mapped_column(Text, default="")
    context_before: Mapped[str] = mapped_column(Text, default="")
    chunk_text: Mapped[str] = mapped_column(Text, default="")
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    sales_embedding_gjld_q3e8b: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    sales_embedding_albl_tev4: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class SalesCaseRAGEvent(Base):
    """销售案例 RAG 运行事件：记录检索命中、注入使用和效果统计所需字段。"""
    __tablename__ = "sales_case_rag_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, default="")
    reference_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    scores_json: Mapped[str] = mapped_column(Text, default="[]")
    max_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    avg_score: Mapped[float] = mapped_column(Float, default=0.0)
    used_reference_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    used_strategy: Mapped[str] = mapped_column(Text, default="")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class LLMCallEmbed(Base):
    """Embedding 模型调用记录：用于追踪向量审核和向量检索的调用。"""

    __tablename__ = "llm_calls_embed"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_invocation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    api_url: Mapped[str] = mapped_column(Text, default="")
    target_table: Mapped[str] = mapped_column(String(128), default="", index=True)
    target_column: Mapped[str] = mapped_column(String(128), default="", index=True)
    target_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    attempt_index: Mapped[int] = mapped_column(Integer, default=1)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=1, index=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=0)
    input_text: Mapped[str] = mapped_column(Text, default="")
    error_type: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    usage_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LLMSafetyVectorMatch(Base):
    """风控向量匹配记录：保存回复与风控规则的相似度明细。"""

    __tablename__ = "llm_safety_vector_matches"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_invocation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    node_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    target_table: Mapped[str] = mapped_column(String(128), default="knowledge_safety_rules", index=True)
    target_column: Mapped[str] = mapped_column(String(128), default="", index=True)
    target_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    rule_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    level: Mapped[str] = mapped_column(Text, default="")
    primary_category: Mapped[str] = mapped_column(Text, default="")
    secondary_category: Mapped[str] = mapped_column(Text, default="")
    standard: Mapped[str] = mapped_column(Text, default="")
    violation: Mapped[str] = mapped_column(Text, default="")
    handling_result: Mapped[str] = mapped_column(Text, default="")
    draft_reply: Mapped[str] = mapped_column(Text, default="")
    similarity: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    match_rank: Mapped[int] = mapped_column(Integer, default=0)
    is_hit: Mapped[int] = mapped_column(Integer, default=0, index=True)
    action: Mapped[str] = mapped_column(String(32), default="pass", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeImportRun(Base):
    """知识库导入记录：记录每次从文件同步到数据库的结果。"""
    __tablename__ = "knowledge_import_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    source_path: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="", index=True)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
