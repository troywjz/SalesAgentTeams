# 项目协作说明

## 项目地图

- `app/`：FastAPI、LangGraph 六 Agent、数据库和 Web API。
- `sales_agent_teams/`：业务 Agent 到 Worker 的契约与适配层。
- `agentteams/`：Worker SOUL、版本化 Skill、打包和本地团队运行器。
- `mcp_servers/`：销售 Bridge MCP 与评估/3D 热力图 MCP。
- `data/`：只可提交公开办公技能示例；私有同名文件由 `.gitignore` 排除。
- `evaluation/`：公开快照、数据集和评估代码；结果目录不提交。
- `submission/preliminary/`：GOAI 初赛提交材料。
- `scripts/setup_project.ps1`、`start_all.ps1`、`stop_all.ps1`：Windows 首次准备与完整生命周期入口；`.runtime/` 只存本地 PID、日志和下载的官方安装器。

## 不可破坏的边界

- 运行时数据库名必须是 `sales_agent_demo`，默认端口 `15432`；禁止连接原会计业务库。
- `.env.example` 默认用于真实模型、三供应商回退和销售案例向量 RAG 展示；所有自动化测试必须显式强制 `DEMO_MODE=true`、`LLM_PROVIDER=demo`、`SALES_RAG_ENABLED=false`，不得调用真实 LLM 或 Embedding API。
- 所有客户可见自动回复必须经过 Safety Agent；付款、合同、退款、发票、企业数据等转人工。
- Skill 改动后同步更新 `sales_agent_teams/bridge.py` 中版本并重建 Worker 包。
- 不提交 `.env`、密钥、真实聊天、私有知识、评估结果或本地绝对路径。
- 生命周期脚本只允许管理 `SalesAgentTeams` 容器与本项目 `.venv` 启动的进程；禁止停止、删除或重建原项目 `sales_agent`。

## 完成前验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\check_competition_readiness.py
.\.venv\Scripts\python.exe scripts\check_open_source.py
git diff --check
```
