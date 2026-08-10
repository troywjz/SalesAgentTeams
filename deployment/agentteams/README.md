# AgentTeams 部署

当前清单使用 AgentTeams `agentteams.io/v1beta1` 的 `Worker`、`Team` 和 `Manager` 资源格式。清单中的 `conversation_worker` 同时作为 Team Leader；它仍然对应原项目的 `ConversationAgent`，没有新增业务 Agent。

## 前置条件

- Docker Desktop 正常运行。
- 已安装官方 AgentTeams，并且 `agt` 命令可用。
- 已构建 Worker 包：

```powershell
python agentteams/build_worker_packages.py
```

- 已启动两个 HTTP MCP 服务：

```powershell
docker compose -f deployment/docker-compose.mcp.yml up --build
```

## 应用清单

清单默认使用 `qwen3.5-plus`，如果你的 AgentTeams 使用其他模型，请在应用前修改所有 `spec.model`，并完成 AgentTeams 自己的 LLM 凭据配置。

```powershell
agt apply -f deployment/agentteams/sales-agent-teams.yaml
agt get workers
agt get teams
```

Worker 通过 `host.docker.internal` 访问宿主机上的 MCP 服务。共享部署时应改为经 Gateway 暴露的 HTTPS MCP 地址，并把真实凭据留在 Gateway，不写入 Worker 包或 Git。
