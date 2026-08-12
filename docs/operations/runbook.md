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

原销售项目的 `8000`、`5432`、`6379` 不属于本比赛 Demo，不应停止、重建或清空。

## 标准启动

1. `docker compose -f deployment/docker-compose.demo-db.yml up -d`
2. 首次运行 `scripts/setup_demo.ps1`
3. 需要刷新固定样例时运行 `scripts/seed_demo_data.ps1`
4. 运行 `start_demo.cmd`
5. 访问 `/health`，确认 `status=ok`、`llm=demo-fallback`

`seed_demo_data.ps1` 只刷新 `demo-session-001` 至 `010` 等固定公开样例；用户新建的其他 Demo 会话不会被清空。

## 常见故障

- `18100` 无法访问：检查 `Get-NetTCPConnection -LocalPort 18100` 和启动窗口日志。
- 数据库连接失败：检查 `docker compose -f deployment/docker-compose.demo-db.yml ps`，必须为 healthy。
- 页面仍显示旧数据：运行 `scripts/seed_demo_data.ps1`，重启 Web 后强制刷新浏览器。
- 误出现真实模型配置：确认 `.env` 中 `DEMO_MODE=true`、`LLM_PROVIDER=demo`。
- AgentTeams Worker 退出：先确认 18081、18765 可达，再运行 `scripts/start_agentteams_workers.ps1`。

## 回滚

代码回滚不应操作原销售项目数据库。Demo 数据异常时仅重建 `salesagentteams-demo` 项目对应的数据卷，再执行初始化；执行前应确认目标容器名为 `sales-agent-teams-demo-db`。
