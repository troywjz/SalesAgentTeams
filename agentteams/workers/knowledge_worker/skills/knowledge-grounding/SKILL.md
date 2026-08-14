---
name: knowledge-grounding
description: 从企业授权的商品与服务知识快照中检索事实并返回可引用证据。
---

# Knowledge Grounding Skill

版本：1.1.1

## 目的

为回复提供可追踪的商品/服务、价格、交付、FAQ 和 SOP 事实，避免模型补造。

## 输入

客户消息、意图、销售阶段、授权知识引用和检索限制。

## 输出

匹配方案、事实、政策提示、缺失信息、来源和 `knowledge_sufficiency`。

## 触发条件

客户询问商品/服务、价格、交付、流程或方案匹配时在 SOP 决策后触发。

## 依赖工具

Sales Agent Bridge MCP 的 `run_knowledge_agent`、企业授权或公开演示知识快照、`evidence-handoff`。

## 失败处理

知识源不可用或证据不足时返回 `insufficient`，让后续 Worker 澄清或转人工。

## 安全边界

只读取授权知识源；风控规则由 Safety Worker 独占；不读取 `.env`、私有聊天或原会计数据库。

## 复用价值

可替换知识快照复用于商品咨询、售前问答和内部知识助手。

## 多 Agent 流程关系

承接 SOP Worker，向 Conversation 和 Safety Worker提供事实与缺失项。

## 验证

校验每条事实有来源，价格来自 SKU，缺失项明确标记，安全规则未混入普通知识检索。
