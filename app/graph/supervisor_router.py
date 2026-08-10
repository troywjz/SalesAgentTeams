from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.conversation import ConversationState
from app.graph.routing_rules import (
    has_extreme_emotion_keyword,
    has_profile_signal,
    has_strong_handover_keyword,
    is_small_talk,
    looks_like_knowledge_request,
)


# ── 路由名称类型 ──────────────────────────────────────────────
# 四种可能的执行路由，决定哪些 Agent 需要运行

RouteName = Literal[
    "manual_control",   # 人工已接管，自动回复停止
    "force_handover",   # 强制转人工（投诉/极端情绪等）
    "direct_reply",     # 简单寒暄，仅运行 conversation + safety
    "full_auto",        # 完整自动回复链路，按需运行所有 Agent
]


@dataclass(frozen=True)
class SupervisorDecision:
    """调度器的决策结果，描述本次对话应走哪条路由、运行哪些 Agent。

    Attributes:
        route: 路由名称，决定整体执行策略
        run_agents: 各 Agent 是否需要运行的开关字典，
            如 {"intent": True, "safety": True, "knowledge": False}
        parallel_groups: Agent/节点并行执行分组，同一组内可并行，
            不同组间需串行等待。如 [["knowledge", "sop"], ["conversation"]]
            表示 knowledge 和 sop 可并行，conversation 需等前组完成。
        reasons: 决策原因列表，用于日志和可解释性
        requires_llm: 是否需要 LLM 参与（当前均为确定性规则，此字段预留）
    """

    route: RouteName
    run_agents: dict[str, bool]
    parallel_groups: list[list[str]]
    reasons: list[str] = field(default_factory=list)
    requires_llm: bool = False

    def model_dump(self) -> dict[str, Any]:
        """序列化为字典，用于日志输出和 API 响应。"""
        return asdict(self)


def decide_supervisor_route(
    message: str,
    state: ConversationState,
) -> SupervisorDecision:
    """确定性调度器：基于关键词匹配做低成本路由判断，不调用 LLM。

    决策优先级（从高到低）：
    1. manual_control  — 会话已被人工接管，停止自动回复
    2. force_handover  — 命中强转人工关键词或极端情绪关键词
    3. direct_reply    — 短寒暄且无知识/画像需求，仅跑 conversation + safety
    4. full_auto       — 其他所有情况，按需运行完整链路

    Args:
        message: 用户原始消息
        state: 当前会话状态（含 transfer_flag、客户画像等）

    Returns:
        SupervisorDecision 调度决策，包含路由、Agent 运行计划和原因
    """
    reasons: list[str] = []

    # 优先级 1：人工已接管，所有自动回复必须停止
    if state.transfer_flag:
        return SupervisorDecision(
            route="manual_control",
            run_agents=_agent_plan(),  # 全部关闭
            parallel_groups=[],
            reasons=["当前会话已由人工接管，自动回复不应继续运行"],
        )

    # 优先级 2a：命中强转人工关键词（投诉/退款/报警/立即购买等）
    # 直接进入 handover，不再运行 LLM，避免自动回复继续介入
    if has_strong_handover_keyword(message):
        reasons.append("命中强转人工关键词")
        return SupervisorDecision(
            route="force_handover",
            run_agents=_agent_plan(),
            parallel_groups=[],
            reasons=reasons,
        )

    # 优先级 2b：命中极端负面情绪关键词
    # 直接进入 handover，由人工安抚
    if has_extreme_emotion_keyword(message):
        reasons.append("命中强负面情绪关键词")
        return SupervisorDecision(
            route="force_handover",
            run_agents=_agent_plan(),
            parallel_groups=[],
            reasons=reasons,
        )

    # 优先级 3 之前的预判：检测是否需要知识检索和画像更新
    needs_knowledge = looks_like_knowledge_request(message)
    needs_profile_update = has_profile_signal(message)
    small_talk = is_small_talk(message)

    # 优先级 3：短寒暄 + 无知识/画像需求
    # 跳过 intent/sop/knowledge，仅生成轻量回复并做风控
    # 先 conversation 再 safety 串行执行
    if small_talk and not needs_knowledge and not needs_profile_update:
        reasons.append("短寒暄，可直接生成轻量回复并做风控")
        return SupervisorDecision(
            route="direct_reply",
            run_agents=_agent_plan(conversation=True, safety=True),
            parallel_groups=[["conversation"], ["safety"]],
            reasons=reasons,
        )

    # 优先级 4：完整自动回复链路
    # 记录触发原因（知识需求 / 画像需求 / 兜底默认）
    if needs_knowledge:
        reasons.append("用户问题可能依赖商品、FAQ、SOP 或政策知识")
    if needs_profile_update:
        reasons.append("用户消息包含画像或长期记忆线索")
    if not reasons:
        reasons.append("未命中低成本跳过规则，使用完整自动回复链路")

    # 并行分组设计：
    # 第 1 组 [intent]：先识别语义并决定是否扇出
    # 第 2 组 [knowledge, sop]：按需并行
    # 第 3 组 [conversation]：依赖前面所有可选上下文，需串行
    # 第 4 组 [safety]：依赖草稿回复，需串行
    # 第 5 组 [finalize, memory_update]：send 后扇出，其中 memory_update 调 LLM
    return SupervisorDecision(
        route="full_auto",
        run_agents=_agent_plan(
            intent=True,
            sop=True,
            knowledge=needs_knowledge,
            conversation=True,
            safety=True,
            memory_update=True,
        ),
        parallel_groups=[
            ["intent"],
            ["knowledge", "sop"] if needs_knowledge else ["sop"],
            ["conversation"],
            ["safety"],
            ["finalize", "memory_update"],
        ],
        reasons=reasons,
    )


# ── 内部辅助函数 ──────────────────────────────────────────────


def _agent_plan(
    *,
    intent: bool = False,
    sop: bool = False,
    knowledge: bool = False,
    conversation: bool = False,
    safety: bool = False,
    memory_update: bool = False,
) -> dict[str, bool]:
    """生成 Agent 运行计划字典，未指定的 Agent 默认不运行。

    这是一个便捷构造器，避免手写完整的六键字典。
    所有参数默认 False，调用时只需指定需要运行的 Agent。
    """
    return {
        "intent": intent,
        "sop": sop,
        "knowledge": knowledge,
        "conversation": conversation,
        "safety": safety,
        "memory_update": memory_update,
    }
