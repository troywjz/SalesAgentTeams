---
name: evidence-handoff
description: 为所有 Worker 统一记录版本、证据、错误和人工交接边界。
---

# Evidence Handoff Skill

版本：1.1.0

## 目的

提供跨 Worker 的统一可观测信封，使任务链可重建、失败可定位、结论可审计。

## 输入

任务 ID、Worker ID、Skill 版本、工具调用、输入摘要和输出摘要。

## 输出

证据引用、状态、错误、重试次数、审批状态和人工交接信息。

## 触发条件

每次 Worker 或 MCP 工具调用前后触发。

## 依赖工具

AgentTeams 任务信封、应用 Trace/Log 记录和结构化 WorkerResult。

## 失败处理

证据写入失败时保留内存错误并阻止对外宣称“已验证”。

## 安全边界

不得记录密钥、完整敏感聊天、数据库连接串或未脱敏原始文件。

## 复用价值

作为公共治理层，可复用于所有 AgentTeams 业务团队。

## 多 Agent 流程关系

贯穿 Manager、Team Leader、六 Worker 与 MCP，负责证据和人工接管的连续传递。

## 验证

按 `task_id` 和 `turn_id` 重建链路，检查版本、工具、错误和审核结论均可关联。
