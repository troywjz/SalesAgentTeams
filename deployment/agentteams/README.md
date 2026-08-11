# AgentTeams 部署

当前清单使用 AgentTeams `agentteams.io/v1beta1` 的 `Worker`、`Team` 和 `Manager` 资源格式。清单中的 `conversation_worker` 同时作为 Team Leader；它仍然对应原项目的 `ConversationAgent`，没有新增业务 Agent。

## 前置条件

- Docker Desktop 正常运行。
- 已安装官方 AgentTeams。`agt` 属于 AgentTeams Controller CLI，不是 Python 依赖；Docker 安装模式通过 `docker exec agentteams-controller agt ...` 调用。
- 已构建并提交 Worker 包；修改 Worker 的 Skill 后重新生成压缩包并推送到 GitHub：

```powershell
python agentteams/build_worker_packages.py
```

- 已启动两个 HTTP MCP 服务：

```powershell
docker compose -f deployment/docker-compose.mcp.yml up --build
```

## 应用清单

清单使用 `deepseek-v4-flash`。当前兼容配置为 Manager 使用 `openclaw`，六个销售 Worker 使用 `qwenpaw`；Worker 包从清单中的 GitHub Raw HTTPS 地址下载。如果你的 AgentTeams 镜像提供不同的运行时组合，可以相应调整 `spec.model` 和 `spec.runtime`，并完成 AgentTeams 自己的 LLM 凭据配置。

Docker 安装模式下，把清单复制到 Controller 容器后应用：

```powershell
docker cp deployment/agentteams/sales-agent-teams.yaml agentteams-controller:/tmp/sales-agent-teams.yaml
docker exec agentteams-controller agt apply -f /tmp/sales-agent-teams.yaml
docker exec agentteams-controller agt get workers
docker exec agentteams-controller agt get teams
```

Worker 通过 `host.docker.internal` 访问宿主机上的 MCP 服务。共享部署时应改为经 Gateway 暴露的 HTTPS MCP 地址，并把真实凭据留在 Gateway，不写入 Worker 包或 Git。
