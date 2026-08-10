---
name: team-lead-coordination
description: 作为 AgentTeams Team Leader 分派销售任务、汇总 Worker 输出并维护可审计交接。
---

# Team Lead Coordination Skill

版本：1.0.0

## 输入

Manager 任务、会话状态、Worker 角色清单和当前任务证据。

## 输出

返回可追踪的子任务、依赖关系、汇总结果、失败 Worker 和下一步动作。

## 触发与边界

收到 Manager 任务时触发。只调用声明过的六个 Worker 和 MCP 工具，不访问密钥，不隐藏 Agent 间消息，不绕过人工接管条件。

## 失败处理

子任务超时或失败时保留错误和证据，按依赖关系重试一次；仍失败则交给 Manager 或人工处理。

## 验证与复用

验证每个子任务有唯一 ID、输入输出可关联、依赖已满足。可复用于其他业务多 Agent 团队。
