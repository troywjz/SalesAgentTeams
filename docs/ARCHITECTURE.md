# SalesAgentTeams 架构

## 定位

SalesAgentTeams 是一个企业销售多智能体协同 Demo。原有 LangGraph 负责销售状态、路由、并行节点、风控和落库逻辑；AgentTeams 负责 Worker 生命周期、跨 Agent 协作、可见交接和容器化运行。

AgentTeams 不替换 LangGraph。`sales_agent_teams.bridge` 是两者之间的适配层，保证原项目 Agent 可以被六个 Worker 复用。

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
