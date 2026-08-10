from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    SalesGraphNodes,
    route_after_intent,
    route_after_knowledge,
    route_after_safety,
    route_after_supervisor,
)
from app.graph.state import SalesGraphState
from app.core.config import Settings
from app.knowledge import KnowledgeLoader
from app.knowledge.safety_vector import SafetyVectorReviewer
from app.llm import LLMClient
from app.sales_rag import SalesCaseRAGService


# 内存级检查点存储器，用于保存每一步的图状态快照
# 同一进程内多次调用可恢复到任意断点，适合开发调试和单实例部署
# 生产环境可替换为数据库持久化的 Checkpointer（如 PostgresSaver）
_CHECKPOINTER = MemorySaver()


def build_sales_graph(
    llm_client: LLMClient,
    knowledge_loader: KnowledgeLoader | None = None,
    sales_case_rag_service: SalesCaseRAGService | None = None,
    *,
    safety_vector_reviewer: SafetyVectorReviewer | None = None,
    settings: Settings | None = None,
    enable_checkpoint: bool = True,
    include_memory_update: bool = True,
):
    """构建并编译销售对话 LangGraph。

    图的拓扑结构::

        START
          ↓
        init            ── 初始化状态、加载知识库上下文
          ↓
        supervisor_router ── 低成本规则调度
          ↓
        intent / conversation / handover
          ↓
        route_after_intent ── 按需扇出到 sop、knowledge、sales_case_rag
          ↓ (条件路由)
        context_gate    ── 汇聚可选上下文
          ↓
    conversation / handover
        ↓
      safety          ── 向量风控（有向量数据时）+ SafetyAgent
        ↓ (条件路由)
    ┌───────┼───────┐
    ↓       ↓       ↓
  final_reply rewrite_reply  handover
  (直接输出) (改写后输出)   (转人工)
    ↓       ↓       ↓
    └───────┼───────┘
            ↓
         send        ── 发送回复
          ↓
      finalize + memory_update
            ↓
           END

    Args:
        llm_client: LLM 客户端实例，注入到所有 Agent 节点
        knowledge_loader: 知识库加载器，为 None 时使用默认实现
        enable_checkpoint: 是否启用检查点持久化，默认开启。
            关闭后图变为无状态，适合无状态 API 部署场景。
        include_memory_update: 是否把 memory_update 放进主图。
            实时 WebSocket 链路会关闭此项，在回复发送后异步补跑记忆更新。

    Returns:
        编译后的 LangGraph Runnable，可直接调用 ``.invoke()`` 或 ``.astream()`` 执行
    """
    nodes = SalesGraphNodes(
        llm_client,
        knowledge_loader,
        safety_vector_reviewer=safety_vector_reviewer,
        sales_case_rag_service=sales_case_rag_service,
        settings=settings,
    )
    graph = StateGraph(SalesGraphState)

    # ── 注册所有节点 ──────────────────────────────────────────
    # 节点名称即图中的标识符，在条件路由的映射表中需保持一致

    graph.add_node("init", nodes.init)
    graph.add_node("supervisor_router", nodes.supervisor_router)
    graph.add_node("intent", nodes.intent)
    graph.add_node("sop", nodes.sop)
    graph.add_node("knowledge", nodes.knowledge)
    graph.add_node("sales_case_rag", nodes.sales_case_rag)
    graph.add_node("context_gate", nodes.context_gate)
    graph.add_node("conversation", nodes.conversation)
    graph.add_node("safety", nodes.safety)
    graph.add_node("rewrite_reply", nodes.rewrite_reply)
    graph.add_node("handover", nodes.handover)
    graph.add_node("final_reply", nodes.final_reply)
    graph.add_node("send", nodes.send)
    graph.add_node("finalize", nodes.finalize)
    graph.add_node("memory_update", nodes.memory_update)

    # ── 定义边（节点间的流转关系） ────────────────────────────

    # 入口边：图的起始点指向初始化节点
    graph.add_edge(START, "init")

    graph.add_edge("init", "supervisor_router")
    graph.add_conditional_edges(
        "supervisor_router",
        route_after_supervisor,
        {
            "intent": "intent",
            "conversation": "conversation",
            "handover": "handover",
        },
    )

    # 条件边 1：意图识别之后按需扇出。
    graph.add_conditional_edges(
        "intent",
        route_after_intent,
        {
            "knowledge": "knowledge",
            "sop": "sop",
            "sales_case_rag": "sales_case_rag",
            "conversation": "conversation",
            "handover": "handover",
        },
    )

    # fan-in：知识、SOP 和销售案例 RAG 均为可选节点，执行后汇聚到 context_gate。
    graph.add_edge("knowledge", "context_gate")
    graph.add_edge("sop", "context_gate")
    graph.add_edge("sales_case_rag", "context_gate")

    # 条件边 2：上下文汇聚之后根据 SOP 和知识充分性决定走向。
    graph.add_conditional_edges(
        "context_gate",
        route_after_knowledge,
        {
            "conversation": "conversation",       # 知识充足 → 生成回复
            "handover": "handover",               # 需人工介入 → 转人工
        },
    )

    # conversation 固定流向风控审核
    graph.add_edge("conversation", "safety")

    # 条件边 2：风控审核之后的三路分支
    # route_after_safety 根据 safety.action 决定走向
    graph.add_conditional_edges(
        "safety",
        route_after_safety,
        {
            "final_reply": "final_reply",   # 通过/拦截 → 最终输出
            "rewrite": "rewrite_reply",     # 需改写 → 重新生成
            "handover": "handover",         # 需转人工 → 转人工
        },
    )

    # 改写后重新审核：rewrite_reply → safety（而非直接 finalize）。
    # rewrite_reply 会优先复用 SafetyAgent 给出的 revised_reply，
    # 缺失时才再次调用 ConversationAgent，避免不必要的二次 LLM 调用。
    graph.add_edge("rewrite_reply", "safety")

    # 成功回复先经过 send，再做同步收尾。实时链路会将记忆更新放到图外异步执行，
    # 避免客户可见回复被 MemoryAgent 阻塞。
    graph.add_edge("final_reply", "send")
    graph.add_edge("send", "finalize")
    if include_memory_update:
        graph.add_edge("send", "memory_update")

    # 转人工直接进入同步收尾，不发送 AI 回复。
    graph.add_edge("handover", "finalize")

    # 出口边：收尾后结束图执行。开启 memory_update 时两个后续节点都指向 END。
    graph.add_edge("finalize", END)
    if include_memory_update:
        graph.add_edge("memory_update", END)

    # ── 编译图 ────────────────────────────────────────────────
    # compile() 验证拓扑合法性（无悬空节点、条件路由映射完整等），
    # 并返回可执行的 Runnable 对象
    return graph.compile(
        checkpointer=_CHECKPOINTER if enable_checkpoint else None,
    )
