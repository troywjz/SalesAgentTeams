# SalesAgentTeams

面向通用 To C 网络销售场景的多智能体协同系统，也是 [GOAI Agent Infra](https://goaihz.com/tracks?track=infra) 赛道的可运行作品。企业只需适配商品或服务知识、销售 SOP、优秀案例、风险规则和渠道数据，即可复用核心流程。

系统将每轮对话沉淀为客户画像、销售阶段和后续任务：LangGraph 负责业务路由、并行检索、安全复审、落库与调度；六个业务 Agent 映射为六个 AgentTeams Worker；10 个版本化 Skill 固化能力边界；两个 MCP 提供角色受限工具和离线评估能力。

“自主推进”仅覆盖规则明确的销售流程。复杂报价、敏感承诺、负面情绪、知识不足和模型异常会暂停自动流程并转人工，项目不把自动推进表述为自动成交。

## 三步启动

已验证的一键流程面向 Windows 10/11。需要 Python 3.11+ 和 Docker Desktop；缺失时准备脚本会优先通过 `winget` 安装。

```powershell
# 1. 检查环境、创建虚拟环境、安装依赖并准备镜像
.\setup.cmd

# 2. 编辑 setup.cmd 自动创建的 .env，填写以下三个 Key
# DEEPSEEK_API_KEY=
# ALIYUN_API_KEY=
# SILICONFLOW_API_KEY=

# 3. 启动 Web、数据库、两个 MCP、AgentTeams 和六个 Worker
.\start_all.cmd
```

`.env.example` 已配置正式展示所需的模型接口、`DeepSeek → 阿里云 → SiliconFlow` 回退链、AgentTeams 和向量 RAG。`AGENTTEAMS_LLM_API_KEY` 留空时复用 DeepSeek Key。首次启用 Docker Desktop 时，如系统要求启用 WSL 2、虚拟化或重启，完成后重新运行脚本即可。

停止全部比赛项目服务并保留数据卷：

```powershell
.\stop_all.cmd
```

## 展示入口

| 入口 | 地址 | 本地 Demo 账号 |
|---|---|---|
| 销售端 | `http://127.0.0.1:18100/sales` | `wangjie@salesagent.com` / `123456` |
| 客户模拟端 | `http://127.0.0.1:18100/customer` | 无需登录 |
| 管理员端 | `http://127.0.0.1:18100/admin` | `admin` / `admin123` |
| 健康检查 | `http://127.0.0.1:18100/health` | — |

完整启动后还会提供：

| 服务 | 地址 | 用途 |
|---|---|---|
| Bridge MCP | `http://127.0.0.1:18081/mcp` | 六个角色受限业务工具 |
| Evaluation MCP | `http://127.0.0.1:18082/mcp` | 离线回放、评分和 3D 热力图 |
| AgentTeams | `http://127.0.0.1:18088` | Manager 与团队协作入口 |
| Higress 控制台 | `http://127.0.0.1:18001` | AgentTeams 控制面入口 |

以上账号只适用于本地公开 Demo。公开部署前必须修改默认密码和 `APP_SECRET_KEY`。

## 架构与能力

| 层级 | 实现 |
|---|---|
| 业务流程 | FastAPI + LangGraph；维护客户画像、销售阶段、任务、定时推进与人工接管 |
| 多 Agent 协同 | Memory、Intent、SOP、Knowledge、Conversation/Team Leader、Safety 六 Worker |
| Skill 工程 | 6 个业务 Skill + 团队协调 + 证据交接 + 离线评估 + 3D 热力图，共 10 个版本化 Skill |
| MCP 工具 | Bridge MCP 限制 Worker 工具权限；Evaluation MCP 生成离线评估产物 |
| 数据与 RAG | 独立 PostgreSQL/pgvector 保存公开 Demo 数据、会话状态、任务和向量索引 |
| 安全与可观测 | Safety 复审、人工接管、节点/模型调用记录、回退轨迹、RAG 命中和错误日志 |

AgentTeams 不替换 LangGraph：前者负责 Worker 生命周期、跨 Agent 协作和可见交接，后者保留销售业务状态机与执行闭环。详细设计见 [架构说明](docs/ARCHITECTURE.md) 和 [Agent Identity 清单](docs/AGENT_IDENTITIES.md)。

## 正式展示与零 API 回归

| 模式 | 配置与用途 |
|---|---|
| 正式展示 | `DEMO_MODE=false`；启用三供应商回退、AgentTeams 和销售案例向量 RAG |
| 零 API 回归 | 验证脚本在进程内强制使用确定性模拟客户端 `DemoLLMClient`，并关闭 AgentTeams 与向量能力，不调用真实 LLM 或 Embedding API |

零 API 回归验证：

```powershell
.\scripts\verify_demo.ps1
```

该脚本依次执行全量测试、六 Worker 确定性试运行、GOAI 就绪检查、开源审计和 Git 空白字符检查；不会修改 `.env`。确定性模拟客户端用于验证编排、接口、数据库、MCP 和页面链路，不代表真实模型回复质量。

## 数据与安全边界

- 比赛 Web 固定使用 `18100`，独立数据库固定使用 `15432/sales_agent_demo`；运行时护栏拒绝其他数据库名。
- `DEMO_SEED_DATA=true` 只幂等导入仓库内可替换的公开销售样例；不会访问原项目数据库或历史会话。
- 仓库不提交 `.env`、API Key、真实聊天、私有知识、评估原始结果或本地绝对路径。
- Evaluation MCP 没有人工评分时只生成回放和盲评模板，不补造分数；历史离线盲评不等同于转化率提升。
- 生命周期脚本只管理 `SalesAgentTeams` 的进程、容器和数据卷，不停止或删除其他项目。

## 文档与比赛材料

| 文档 | 内容 |
|---|---|
| [方案说明](submission/preliminary/方案说明.md) | 场景闭环、AgentTeams 映射、Skill/MCP/RAG、安全与部署设计 |
| [作品简介（500 字内）](submission/preliminary/作品简介_500字.md) | 初赛作品简介正文 |
| [初赛方案 PPT](submission/preliminary/SalesAgentTeams_初赛方案.pptx) | 初赛路演材料 |
| [Agent Identity 清单](docs/AGENT_IDENTITIES.md) | 六个 Agent 的身份、能力边界和协同关系 |
| [GOAI 合规与得分映射](submission/preliminary/GOAI合规与得分映射.md) | 官网要求与项目证据对应关系 |
| [运行证据清单](submission/preliminary/运行证据清单.md) | 启动、测试、MCP、AgentTeams 和真实 API 试运行证据 |
| [历史评测与验证报告](submission/preliminary/历史评测与验证报告.md) | 离线盲评结论、短板与适用边界 |
| [运维手册](docs/operations/runbook.md) | 单组件调试、故障排查、回滚和数据保护 |
| [开源声明](submission/preliminary/开源声明.md) | 数据、密钥、第三方依赖和公开范围 |

## 许可证

项目使用 [GNU AGPL-3.0](LICENSE)。公开仓库只包含可替换的演示数据和可验证工程材料。
