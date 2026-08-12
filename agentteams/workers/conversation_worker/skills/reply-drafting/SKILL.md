---
name: reply-drafting
description: 基于意图、SOP 和知识证据生成单问题、可推进且可审核的销售回复草稿。
---

# Reply Drafting Skill

版本：1.1.0

## 目的

生成简短、自然、带一个明确下一步的客户回复草稿。

## 输入

客户消息、意图、阶段、下一步动作、知识证据、案例引用和授权记忆。

## 输出

`thinking`、`final_reply` 和可选策略说明；输出仍是待审核草稿。

## 触发条件

意图、SOP 和必要知识结果可用后触发。

## 依赖工具

Sales Agent Bridge MCP 的 `run_conversation_agent`、`evidence-handoff`，可选销售案例 RAG 引用。

## 失败处理

证据不足时只提出澄清问题；生成失败时由 Team Leader 重试一次或转人工。

## 安全边界

不得承诺未经证实的价格、优惠、提效、就业或交易结果；不得绕过 Safety Worker。

## 复用价值

可复用于客服、售前和客户成功的受控回复生成。

## 多 Agent 流程关系

汇总 Intent、SOP、Knowledge 和 Memory 输出，草稿必须交给 Safety Worker。

## 验证

校验回复非空、问题数量受控、事实来自证据且未出现高风险外部动作。
