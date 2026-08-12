---
name: team-lead-coordination
description: 作为 AgentTeams Team Leader 分派销售任务、汇总 Worker 输出并维护可审计交接。
---

# Team Lead Coordination Skill

版本：1.1.0

## 目的

把 Manager 任务拆分为六 Worker 可执行子任务，并按依赖汇总结果。

## 输入

Manager 任务、会话状态、Agent Identity 清单、Worker 能力和当前证据。

## 输出

子任务、依赖关系、汇总结果、失败 Worker、证据和下一步动作。

## 触发条件

AgentTeams Manager 把客户咨询或验证任务交给销售 Team 时触发。

## 依赖工具

AgentTeams 团队消息、Sales Agent Bridge MCP、六个业务 Skill 和 `evidence-handoff`。

## 失败处理

子任务超时或失败时保留错误，按依赖重试一次；仍失败则交给 Manager 或人工。

## 安全边界

只调用声明过的 Worker 与 MCP 工具，不读取密钥，不隐藏消息，不绕过人工接管和 Safety Worker。

## 复用价值

可通过替换 Worker 清单复用于其他有审核闭环的业务团队。

## 多 Agent 流程关系

是 Manager 的唯一团队入口；调度 Memory、Intent、SOP、Knowledge、Conversation、Safety 并汇总闭环。

## 验证

校验每个子任务有唯一 ID、依赖已满足、输出可关联、最终结果含审核和证据状态。
