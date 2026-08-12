# 运行与故障处理

## 端口与容器

| 组件 | 端口 | 必需性 | 用途 |
|---|---:|---|---|
| 比赛 Web | 18100 | 演示必需 | 销售端、客户端、管理员端、API |
| Demo PostgreSQL | 15432 | 演示必需 | 只保存办公技能 Demo 数据和对话 |
| Sales Bridge MCP | 18081 | AgentTeams/MCP 演示 | 六个角色受限工具 |
| Evaluation MCP | 18082 | 评估可视化演示 | 回放、评分和 3D 热力图 |
| Worker 包服务 | 18765 | AgentTeams 部署 | 只读公开 Worker zip |
| AgentTeams Controller | 18001 | AgentTeams 控制台 | 登录和资源管理 |
| AgentTeams Element | 18088 | AgentTeams 演示 | Manager/Worker 协作界面 |
| AgentTeams Manager | 18888 | AgentTeams 内部管理 | 本机回环访问 |

原销售项目的 `8000`、`5432`、`6379` 不属于本比赛 Demo，不应停止、重建或清空。

## 首次准备

1. 双击 `setup.cmd`。脚本检查或安装 Python 3.11+、Docker Desktop、Compose 和 Python 依赖，构建 Worker/MCP 工件，并在缺失时从 `.env.example` 生成 `.env`。
2. 按需要填写 Web 模型和 AgentTeams 模型配置。AgentTeams 控制面必须使用真实可用的模型 Key；不展示 AgentTeams 时设置 `AGENTTEAMS_ENABLED=false`。
3. 双击 `start_all.cmd`。首次启动 AgentTeams 时，会下载固定 Git 提交的官方安装器、校验 SHA-256 后执行非交互安装。

## 标准启停

- `start_all.cmd`：依次确保 Docker、数据库、Web、MCP、Worker 包服务、Controller、Manager 和六 Worker 就绪。
- `stop_all.cmd`：按相反顺序停止本项目服务，保留所有数据卷和容器。
- `.runtime/`：保存宿主机进程元数据和日志；已加入 `.gitignore`，关停脚本通过 PID、启动时间和虚拟环境路径三重校验，避免结束无关 Python 进程。
- AgentTeams 首次安装只把 `.runtime/agentteams-share/` 挂载给 Manager，不挂载项目根目录；`.env` 和 API Key 不会通过宿主机共享目录暴露给 Worker。
- 需要刷新固定样例时单独运行 `scripts/seed_demo_data.ps1`；普通启停不会重置用户新建的 Demo 会话。

`seed_demo_data.ps1` 只刷新 `demo-session-001` 至 `010` 等固定公开样例；用户新建的其他 Demo 会话不会被清空。

## 常见故障

- `18100` 无法访问：检查 `Get-NetTCPConnection -LocalPort 18100` 和启动窗口日志。
- 启动窗口提示端口被占用：先运行 `stop_all.cmd`；仍占用时根据提示检查该端口的非项目进程，脚本不会强制结束未知进程。
- 数据库连接失败：检查 `docker compose -f deployment/docker-compose.demo-db.yml ps`，必须为 healthy。
- 页面仍显示旧数据：运行 `scripts/seed_demo_data.ps1`，重启 Web 后强制刷新浏览器。
- 正式展示仍出现本地模型：运行 `.venv\Scripts\python.exe scripts\check_runtime_config.py`，确认 `.env` 中 `DEMO_MODE=false`、`LLM_PROVIDER=deepseek` 且 `DEEPSEEK_API_KEY` 已填写；完整重启后检查 `/health` 的 `llm` 字段。
- 需要零 API 排障：运行 `scripts\verify_demo.ps1`；它只在当前验证进程中强制 Demo 模式，不修改 `.env`。
- AgentTeams Worker 退出：重新运行 `start_all.cmd`；脚本会检查 18081、18765、Controller/Manager 和 Worker 内部 QwenPaw API，而非只判断容器是否为 `Up`。
- Docker Desktop 未运行：`start_all.cmd` 会自动启动并等待最多 180 秒；若失败，检查 WSL 2、虚拟化和 Docker Desktop 状态。
- Python 或 requirements 变化：`start_all.cmd` 会比较 `requirements.txt` 哈希并自动重新执行环境准备。

## 回滚

代码回滚不应操作原销售项目数据库。`stop_all.cmd` 只停机、不删容器和卷。Demo 数据异常时才考虑重建 `salesagentteams-demo` 项目对应的数据卷；执行前应确认目标容器名为 `sales-agent-teams-demo-db` 并单独备份。
