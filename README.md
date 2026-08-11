# SalesAgentTeams

企业销售多智能体协同系统，面向 GOAI Agent Infra 赛道。

本项目将已有销售智能体的六个业务 Agent 映射为六个 AgentTeams Worker，并通过 Skill 和 MCP 形成可审计的协作链路。原有 LangGraph 保留为业务流程内核，AgentTeams 负责外层 Worker 协作、状态传递和运行环境。

## 快速运行

要求：Windows 10/11、Python 3.12+。使用 UTF-8 终端。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\run_demo_team.py
```

`run_demo_team.py` 使用本地演示模型，不需要外部 API，应该输出六个 Worker 的运行轨迹、最终回复和安全交接状态。

## 离线评估

公开样例位于 `evaluation/datasets/demo_cases.csv`。运行原始评估：

```powershell
.\.venv\Scripts\python.exe evaluation\run.py --input-csv evaluation\datasets\demo_cases.csv --demo
```

也可以通过 `sales-evaluation-insights-mcp` 调用 `run_offline_evaluation`、`score_offline_evaluation` 和 `generate_3d_heatmap`。评估不会读取私有数据，不会在没有人工评分时生成虚假分数。

公开流程演示（其中评分标签是流水线测试值，不是正式评估结论）：

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_evaluation_pipeline.py
```

## MCP

本地 stdio：

```powershell
.\.venv\Scripts\python.exe -m mcp_servers.evaluation_insights --transport stdio
.\.venv\Scripts\python.exe -m mcp_servers.sales_agent_bridge --transport stdio
```

Docker HTTP：

```powershell
docker compose -f deployment/docker-compose.mcp.yml up --build
```

两个服务分别监听 `18081` 和 `18082`，供 AgentTeams 或 MCP 客户端使用。

## AgentTeams

```powershell
.\.venv\Scripts\python.exe agentteams\build_worker_packages.py
```

然后安装官方 AgentTeams 并应用。`agt` 是 AgentTeams Controller 提供的 CLI，不需要写入 Python `requirements.txt`；Docker 安装模式通过 Controller 容器调用。Worker 包由宿主机的本地只读 HTTP 服务提供给 Worker 容器：

```powershell
.\scripts\start_agentteams_package_server.ps1
docker cp deployment/agentteams/sales-agent-teams.yaml agentteams-controller:/tmp/sales-agent-teams.yaml
docker exec agentteams-controller agt apply -f /tmp/sales-agent-teams.yaml
.\scripts\start_agentteams_workers.ps1
```

`agt apply` 后建议执行 Worker 健康检查脚本；它会逐个启动退出的 Worker，并同时检查 Docker 状态和容器内 QwenPaw `/api/version`。应用前需要准备 AgentTeams 的 LLM 配置、Docker Desktop 和两个 HTTP MCP 服务。详细映射见 `docs/ARCHITECTURE.md`。

Worker 包服务需要在 `agt apply` 以及后续 Worker 重启期间保持运行；它只提供仓库中的公开 zip 包，不读取密钥或业务数据库。

## 质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\check_open_source.py
git diff --check
```

## 比赛材料

初赛简介、方案 PPT/PDF、运行证据和开源说明位于 `submission/preliminary/`。

## 许可证

本项目使用 AGPL-3.0。原始销售 Demo 来源、第三方依赖和公开数据说明见 `LICENSE`、`docs/OPEN_SOURCE_CHECKLIST.md` 及比赛材料。
