# GOAI Agent Infra 合规与得分映射

依据官方赛道要求，本项目把每项得分点映射到可运行代码或可复核材料。

| 评分维度 | 项目实现 | 证据 |
|---|---|---|
| 场景价值与复用性 25% | 服务通用 To C 网络销售；将对话转化为客户状态、销售阶段和后续任务，企业知识、SOP、案例、风控与渠道数据均可适配 | README、数据契约、方案 PPT |
| 多 Agent 闭环 25% | 六 Worker、Team Leader、统一任务信封、并行检索、Safety 审核、人工接管、Memory 更新和持久化跟进 | AgentTeams 清单、Bridge MCP、运行轨迹 |
| Skill 工程与复用 25% | 10 个版本化 Skill，全部包含目的、输入输出、触发、依赖、失败、安全、复用、流程关系和验证 | `agentteams/workers/**/SKILL.md`、就绪检查脚本 |
| 工程验证与安全 20% | 独立数据库硬护栏、正式展示门禁、零 API 回归、角色受限 MCP、Trace/Log、开源审计和失败转人工 | 测试、MCP 契约、运行报告 |
| 开源 5% | AGPL-3.0、完整运行入口、示例数据、依赖、材料和无密钥审计 | GitHub、LICENSE、开源声明 |

必选项已满足：不少于 3 个 Agent（实际 6 个在线 Worker）、Agent Identity 清单、AgentTeams 团队设计、至少 1 个 Skill（实际 10 个）、端到端闭环。上下文能力同时实现受控记忆、知识检索和轨迹观测；MCP 作为加分工程能力提供两个可运行服务。

运行 `python scripts/check_competition_readiness.py` 会机械校验 Worker 数量、Skill 必填章节、MCP 工具、独立数据库、正式展示配置门禁、旧业务数据残留和初赛材料存在性。`scripts/verify_demo.ps1` 则强制切换到零 API 模式执行回归，避免验证过程产生模型费用。
