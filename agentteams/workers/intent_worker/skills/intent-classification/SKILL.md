---
name: intent-classification
description: 从 To C 网络销售咨询中识别意图、购买意愿、情绪和置信度。
---

# Intent Classification Skill

版本：1.1.1

## 目的

把客户自然语言转换为可路由、可验证的结构化意图，不直接回答客户。

## 输入

`message`、`conversation_state`、`task_id`、`turn_id`。

## 输出

`intent_category`、`purchase_intent`、`emotion`、`confidence`、`reason`。

## 触发条件

每次新客户消息进入完整自动流程时触发；确定性强制转人工和简单寒暄可由 Supervisor 跳过以节省模型调用。

## 依赖工具

Sales Agent Bridge MCP 的 `run_intent_agent`，以及 `evidence-handoff` 公共 Skill。

## 失败处理

输入缺失或模型失败时返回 `failed` 证据；无法判断时返回低置信度并请求补充信息，不静默猜测。

## 安全边界

只做结构化判断，不读取未授权知识、不执行交易、不生成客户可见承诺。

## 复用价值

可复用于客服分流、售前资格判断和线索分级。

## 多 Agent 流程关系

输出交给 SOP Worker 和 Team Leader；其结论不能绕过 Knowledge 与 Safety Worker。

## 验证

固定样例校验字段完整性、枚举值、置信度范围和失败状态可追踪。
