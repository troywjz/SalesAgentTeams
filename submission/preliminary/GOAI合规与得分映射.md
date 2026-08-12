# GOAI Agent Infra 合规与得分映射

依据官方赛道要求，本项目把每项得分点映射到可运行代码或可复核材料。

| 评分维度 | 项目实现 | 证据 |
|---|---|---|
| 场景价值与复用性 25% | 办公技能咨询涵盖个人学习、企业流程、价格异议、隐私和交易接管；知识快照可替换 | README、公开数据、方案 PPT |
| 多 Agent 闭环 25% | 六 Worker、Team Leader、统一任务信封、工具调用、Safety 审核、人工接管和 Memory 更新 | AgentTeams 清单、Bridge MCP、运行轨迹 |
| Skill 工程与复用 25% | 10 个版本化 Skill，全部包含目的、输入输出、触发、依赖、失败、安全、复用、流程关系和验证 | `agentteams/workers/**/SKILL.md`、就绪检查脚本 |
| 工程验证与安全 20% | 独立数据库硬护栏、默认零 API、角色受限 MCP、Trace/Log、单测、开源审计、失败即转人工 | 测试、MCP 契约、运行报告 |
| 开源 5% | AGPL-3.0、完整运行入口、示例数据、依赖、材料和无密钥审计 | GitHub、LICENSE、开源声明 |

必选项已满足：不少于 3 个 Agent（实际 6 个在线 Worker）、Agent Identity 清单、AgentTeams 团队设计、至少 1 个 Skill（实际 10 个）、端到端闭环。上下文能力同时实现受控记忆、知识检索和轨迹观测；MCP 作为加分工程能力提供两个可运行服务。

运行 `python scripts/check_competition_readiness.py` 会机械校验 Worker 数量、Skill 必填章节、MCP 工具、数据库与零 API 默认值、旧业务数据残留和初赛材料存在性。
