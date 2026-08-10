---
name: evidence-handoff
description: 为所有 Worker 统一记录版本、证据、错误和人工交接边界。
---

# Evidence Handoff Skill

版本：1.0.0

## 输入

任务 ID、Worker ID、Skill 版本、工具调用、输入摘要和输出摘要。

## 输出

结构化证据引用、状态、错误、重试次数和人工交接信息。

## 触发与边界

每次 Worker 调用前后执行。不得记录密钥、完整敏感聊天原文或不可公开的连接信息。

## 失败处理

证据写入失败时保留内存中的错误状态，并阻止对外宣称“已验证”。

## 验证与复用

验证任务链可以按 `task_id` 和 `turn_id` 重建；该 Skill 是所有业务 Skill 的公共治理层。
