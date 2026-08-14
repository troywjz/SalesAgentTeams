# SalesAgentTeams 架构

## 定位

SalesAgentTeams 是一个通用 To C 网络销售多智能体协同系统。企业通过适配商品/服务知识、销售 SOP、优秀案例、风险规则和客户渠道数据接入具体业务，核心 Agent、状态机和协作协议不依赖单一行业。系统的核心状态不只是一段对话历史，还包括客户画像、销售阶段、自动推进状态和后续任务。原有 LangGraph 负责这些销售状态的路由、并行检索、Safety 复审、落库和任务调度；AgentTeams 负责 Worker 生命周期、跨 Agent 协作、可见交接和容器化运行。

AgentTeams 不替换 LangGraph。`sales_agent_teams.bridge` 是两者之间的适配层，保证原项目 Agent 可以被六个 Worker 复用。

“自主推进”只覆盖规则明确的销售流程：依据阶段、SOP 与超时规则生成下一步动作，审核通过后发送并更新任务。强制关键词、知识不足、敏感问题、复杂报价、负面情绪、Safety 审核结果或模型异常都可以进入人工接管；接管期间自动回复和后续触达暂停。

## 六 Worker

| Worker | 领域职责 | MCP 工具 | 主要输出 |
|---|---|---|---|
| `intent_worker` | IntentAgent | `run_intent_agent` | 客户意图和置信度 |
| `sop_worker` | SOPAgent | `run_sop_agent` | 销售阶段和下一步动作 |
| `knowledge_worker` | KnowledgeAgent | `run_knowledge_agent` | 有来源的销售知识 |
| `conversation_worker` | ConversationAgent、Team Leader | `run_conversation_agent` | 待审核回复草稿 |
| `safety_worker` | SafetyAgent | `run_safety_agent` | 放行、改写或人工接管 |
| `memory_worker` | MemoryAgent | `run_memory_agent` | 会话记忆读写结果 |

`conversation_worker` 同时承担 AgentTeams 的 Team Leader 平台角色，但不新增业务 Agent。它负责在团队房间中协调其他五个 Worker，最终草稿仍必须经过 `safety_worker`。

## 协作状态

每个子任务通过统一结构传递：`task_id`、`conversation_id`、`turn_id`、消息、会话状态、授权知识引用和运行模式。每个结果都返回 Worker、Skill 版本、状态、输出、证据引用、人工交接和错误信息。

## MCP 边界

- `sales-agent-bridge-mcp`：访问六个业务 Agent。
- `sales-evaluation-insights-mcp`：运行离线回放、评分和热力图生成。
- stdio 适合本地测试，Streamable HTTP 适合 AgentTeams 通过 MCP Gateway 调用。
- MCP 文件工具只允许访问 `evaluation/`，不会读取 `.env` 或私有数据。

## 运行模式

1. 本地模式：不依赖 AgentTeams 或 Docker，使用 `DemoLLMClient` 运行六 Worker 兼容链路。
2. MCP 模式：使用 Docker Compose 启动两个 MCP 服务。
3. AgentTeams 模式：安装官方 AgentTeams，构建 Worker zip 包，应用 `deployment/agentteams/sales-agent-teams.yaml`。

## 数据与成本边界

- 比赛 Web 固定使用 `18100`，独立 PostgreSQL 固定使用 `15432/sales_agent_demo`；运行时数据库护栏会拒绝任何其他数据库名。
- 原销售项目的会计数据、会话历史、`8000` Web 和 `5432` PostgreSQL 不在比赛项目写入范围内。
- `.env.example` 默认以 `DEMO_MODE=false`、`LLM_PROVIDER=deepseek`、`LLM_PROVIDER_FALLBACK=aliyun,siliconflow` 和销售案例向量 RAG 进行正式展示；启动前门禁要求三个供应商 Key/URL/模型与 Embedding 配置齐全。自动化验证强制切换到本地 Demo 模型并关闭向量能力，禁止产生外部调用。
- Supervisor 对强制转人工和简单寒暄走确定性路由；完整链路再调用所需 Agent，减少无效 token。
