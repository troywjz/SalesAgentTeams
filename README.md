# SalesAgentTeams

面向 GOAI Agent Infra 赛道的办公技能培训销售多智能体系统。六个业务 Agent 一一映射为六个 AgentTeams Worker；LangGraph 保留为业务流程内核，AgentTeams 负责团队协作，Skill 固化能力边界，MCP 提供角色受限工具和离线评估可视化。

公开配置默认使用真实模型正式展示：Web 使用 `18100`，独立 PostgreSQL 使用 `15432/sales_agent_demo`，不会访问原销售项目的 `8000` 或会计业务数据库。复制 `.env.example` 后填写 DeepSeek、阿里云和 SiliconFlow 三个 API Key，即可得到与已验收电脑一致的主模型回退、AgentTeams 和向量 RAG 配置；零 API 测试由独立验证脚本强制切换到本地模型。

## 新电脑首次准备

支持 Windows 10/11。首次拉取或复制项目后，双击 `setup.cmd`，或在 PowerShell 中运行：

```powershell
.\setup.cmd
```

准备脚本会：

- 检查 Python 3.11+、Docker Desktop 和 Docker Compose；缺少 Python 或 Docker Desktop 时优先通过 `winget` 安装。
- 创建 `.venv`，安装并执行 `pip check` 校验 `requirements.txt` 中的全部 Python 依赖。
- `setup.cmd` 会在 `.env` 不存在时先复制 `.env.example`；PowerShell 准备脚本也有同样兜底，均不会覆盖已有配置或 Key。
- 构建六个 Worker 包、拉取 PostgreSQL 镜像并构建两个 MCP 镜像。

系统组件首次安装后如果 Windows 提示启用 WSL 2、虚拟化或重启，应完成提示后再次运行 `setup.cmd`。AgentTeams 控制面需要模型密钥，因此在第一次完整启动时由脚本通过固定提交与 SHA-256 校验后的官方安装器创建；其镜像也固定为本项目已经通过验收的 digest，避免 `latest` 漂移。

然后填写 `.env`：

- 填写 `DEEPSEEK_API_KEY`、`ALIYUN_API_KEY` 和 `SILICONFLOW_API_KEY`。模板已预填 `DEMO_MODE=false`、主模型和三个供应商的接口与模型名。
- AgentTeams 默认启用，`AGENTTEAMS_LLM_API_KEY` 留空即可复用 `DEEPSEEK_API_KEY`；只有使用不同供应商时才需要单独填写。
- Web 默认按 `DeepSeek → 阿里云 → SiliconFlow` 回退，每个配置最多调用一次；只有前一个供应商失败才会调用后一个。MiniMax 仍作为可选供应商保留。
- 暂时只展示 Web、数据库和 MCP 时，可设置 `AGENTTEAMS_ENABLED=false`。

`DEMO_SEED_DATA=true` 仅幂等导入仓库内公开的办公技能培训样例和展示看板，不决定模型模式，也不会连接或修改原会计培训数据库。`SALES_RAG_ENABLED=true` 默认启用办公技能销售案例向量检索，优先复用 `SILICONFLOW_API_KEY`，失败时回退到 `ALIYUN_API_KEY`；首次启动会为公开案例建索引，后续内容未变化时复用已有向量，避免重复计费。`SAFETY_VECTOR_ENABLED=false` 仍保持关闭。

## 一键启动与关停

完整启动：

```powershell
.\start_all.cmd
```

脚本会幂等检查并启动 Docker Desktop、独立 Demo PostgreSQL、数据库表、后台 Web/API、两个 MCP、Worker 包服务、AgentTeams Controller/Manager 和六个 Worker，并逐层执行健康检查。重复运行不会重复创建进程或清空数据。

完整关停：

```powershell
.\stop_all.cmd
```

关停脚本只停止 `SalesAgentTeams` 的宿主机进程和容器，保留 PostgreSQL/AgentTeams 数据卷，不会停止或删除原项目 `sales_agent`。`start_demo.cmd`、`scripts/setup_demo.ps1` 和 `scripts/start_demo.ps1` 作为旧入口继续可用。

页面入口：

- 销售端：`http://127.0.0.1:18100/sales`，账号 `wangjie@salesagent.com`，密码 `123456`
- 客户模拟端：`http://127.0.0.1:18100/customer`，无需登录
- 管理员端：`http://127.0.0.1:18100/admin`，账号 `admin`，密码 `admin123`
- 健康检查：`http://127.0.0.1:18100/health`

以上账号只适用于本地公开 Demo。公开部署前必须修改密码和 `APP_SECRET_KEY`。

## 架构与比赛能力

- 六 Worker：Memory、Intent、SOP、Knowledge、Conversation/Team Leader、Safety。
- 十个版本化 Skill：六个业务 Skill、团队协调、证据交接、离线评估和 3D 热力图。
- 两个 MCP：销售 Agent Bridge（六个角色受限工具）和 Evaluation Insights（回放、评分、热力图）。
- 两类上下文能力：受控会话记忆、授权知识检索；节点调用与 LLM 调用分别留痕。
- 安全闭环：输入路由、任务分解、证据检索、草稿、安全审核、人工接管、记忆更新。

详细边界见 `docs/ARCHITECTURE.md`、`docs/AGENT_IDENTITIES.md` 和 `docs/operations/runbook.md`。

## 零 API 功能验证

```powershell
.\scripts\verify_demo.ps1
```

该脚本会依次执行全量测试、确定性团队试运行、GOAI 就绪检查、开源审计和 Git 空白字符检查，并在任一步失败时立即返回非零结果。

验证脚本会用进程级环境变量强制 `DEMO_MODE=true`、`LLM_PROVIDER=demo` 并关闭向量 RAG，因此即使本机 `.env` 为正式展示配置，也不会调用真实 LLM 或 Embedding。正式服务最多依次尝试 3 个供应商、推理预留为 0，六 Agent 的输出 token 上限也已按结构化结果收紧。

## MCP 与 AgentTeams

一键启动已经包含两个 HTTP MCP：

```powershell
docker compose -f deployment/docker-compose.mcp.yml up --build -d
```

- 销售 Agent Bridge MCP：`http://127.0.0.1:18081/mcp`
- Evaluation Insights MCP：`http://127.0.0.1:18082/mcp`

一键启动也会构建、托管并应用 Worker 包。以下命令仅用于单独调试：

```powershell
.\.venv\Scripts\python.exe agentteams\build_worker_packages.py
.\scripts\start_agentteams_package_server.ps1
docker cp deployment/agentteams/sales-agent-teams.yaml agentteams-controller:/tmp/sales-agent-teams.yaml
docker exec agentteams-controller agt apply -f /tmp/sales-agent-teams.yaml
.\scripts\start_agentteams_workers.ps1
```

`agt` 是 AgentTeams Controller 内的 CLI，不属于 Python 包，因此不写入 `requirements.txt`。AgentTeams Worker 的平台模型配置与 Web Demo 的本地确定性模型是两个独立运行层；`AGENTTEAMS_ENABLED=false` 或零 API 验证不会向 Manager 发送真实模型任务。

## 评估边界

公开数据位于 `evaluation/datasets/demo_cases.csv` 和 `evaluation/knowledge_snapshot/`。Evaluation MCP 在没有人工评分时只生成回放和盲评模板，不补造分数。既有授权离线盲评结论只作为历史证据写入 `submission/preliminary/历史评测与验证报告.md`，本次未重跑，也不把离线分数表述为转化率提升。

## 比赛材料与许可证

初赛简介、PPT/PDF、合规映射、运行证据和开源声明位于 `submission/preliminary/`。项目使用 AGPL-3.0；公开仓库不包含 `.env`、真实聊天、私有知识、模型密钥和原会计业务数据。
