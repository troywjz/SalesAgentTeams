# AgentTeams 部署

当前清单使用 AgentTeams `agentteams.io/v1beta1` 的 `Worker`、`Team` 和 `Manager` 资源格式。清单中的 `conversation_worker` 同时作为 Team Leader；它仍然对应原项目的 `ConversationAgent`，没有新增业务 Agent。

## 前置条件

- Docker Desktop 正常运行。
- 已安装官方 AgentTeams。`agt` 属于 AgentTeams Controller CLI，不是 Python 依赖；Docker 安装模式通过 `docker exec agentteams-controller agt ...` 调用。
- 已构建 Worker 包；修改 Worker 的 Skill 后重新生成压缩包：

```powershell
python agentteams/build_worker_packages.py
```

- 已启动宿主机 Worker 包服务：

```powershell
.\scripts\start_agentteams_package_server.ps1
```

- 已启动两个 HTTP MCP 服务：

```powershell
docker compose -f deployment/docker-compose.mcp.yml up --build
```

## 应用清单

清单使用 `deepseek-v4-flash`。当前兼容配置为 Manager 使用 `openclaw`，六个销售 Worker 使用 `qwenpaw`；Worker 包通过 `host.docker.internal:18765` 从宿主机下载。如果你的 AgentTeams 镜像提供不同的运行时组合，可以相应调整 `spec.model` 和 `spec.runtime`，并完成 AgentTeams 自己的 LLM 凭据配置。

Docker 安装模式下，把清单复制到 Controller 容器后应用：

```powershell
docker cp deployment/agentteams/sales-agent-teams.yaml agentteams-controller:/tmp/sales-agent-teams.yaml
docker exec agentteams-controller agt apply -f /tmp/sales-agent-teams.yaml
.\scripts\start_agentteams_workers.ps1
docker exec agentteams-controller agt get workers
docker exec agentteams-controller agt get teams
```

Worker 启动脚本会顺序拉起退出的 Worker，并检查容器内 QwenPaw 的 `/api/version`。只看 Docker Desktop 的 `Up` 状态不足以判断 Worker 可用；如果发现容器仍在运行但 API 失效，脚本会重启该 Worker。

Worker 包服务需要在 `agt apply` 以及后续 Worker 重启期间保持运行；它只提供公开 zip 包。Worker 通过 `host.docker.internal` 访问宿主机上的 MCP 服务。共享部署时应改为经 Gateway 暴露的 HTTPS MCP 地址，并把真实凭据留在 Gateway，不写入 Worker 包或 Git。

项目根目录的 `start_all.cmd` 已封装以上过程：如果 Controller 不存在，会从官方仓库固定提交下载安装器、校验 SHA-256，并使用本项目已验证的镜像 digest；如果已经安装，则只启动退出的容器。`stop_all.cmd` 会停止 Controller、Manager 和本项目六个 Worker，但保留 AgentTeams 数据卷。首次安装需要 `.env` 中的 `AGENTTEAMS_LLM_API_KEY` 或可复用的供应商 Key。
