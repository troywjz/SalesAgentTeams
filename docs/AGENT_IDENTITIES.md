# Agent Identity 清单

| Worker Identity | AgentTeams 名称 | 职责 | 允许工具 | 禁止事项 | 主要 Skill |
|---|---|---|---|---|---|
| `intent_worker` | `sales-intent-worker` | 识别意图、购买意愿、情绪和置信度 | `run_intent_agent` | 不回答客户、不读取知识、不执行交易 | `intent-classification` |
| `sop_worker` | `sales-sop-worker` | 决定阶段、下一步和接管条件 | `run_sop_agent` | 不生成最终话术、不越过阶段清单 | `sop-decision` |
| `knowledge_worker` | `sales-knowledge-worker` | 检索课程、FAQ、SOP 与案例证据 | `run_knowledge_agent` | 不读风控私库、不补造价格 | `knowledge-grounding` |
| `conversation_worker` | `sales-conversation-worker` | Team Leader；分派任务并生成草稿 | `run_conversation_agent` | 不直接发送未经审核的草稿 | `team-lead-coordination`、`reply-drafting` |
| `safety_worker` | `sales-safety-worker` | 放行、改写或转人工 | `run_safety_agent` | 不删除风险证据、不执行外部动作 | `safety-review` |
| `memory_worker` | `sales-memory-worker` | 读取和更新最小必要会话记忆 | `run_memory_agent` | 不保存密钥、完整敏感原文或未授权个人信息 | `memory-update` |

六个 Worker 都绑定 `evidence-handoff`，统一携带 `task_id`、`turn_id`、Worker、Skill 版本、工具、证据、错误和人工交接信息。Evaluation Operator 是离线评估辅助角色，不计入在线销售六 Worker，也不介入客户回复。
