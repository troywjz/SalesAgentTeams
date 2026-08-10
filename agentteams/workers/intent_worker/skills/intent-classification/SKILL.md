---
name: intent-classification
description: 从销售对话中识别客户意图、购买意愿、情绪和置信度。
---

# Intent Classification Skill

版本：1.0.0

## 输入

`message`、`conversation_state`、`task_id`、`turn_id`。

## 输出

返回 `intent_category`、`purchase_intent`、`emotion`、`confidence`、`reason`。

## 触发与边界

每次新客户消息进入销售流程时触发。只做结构化判断，不回答客户、不读取未授权知识、不进行交易承诺。

## 失败处理

无法判断时返回低置信度并请求补充信息；输入缺失或模型失败时交给 Manager 标记为 `failed`，不得静默使用猜测结果。

## 验证与复用

使用固定意图样例验证字段完整性和置信度范围。该 Skill 可复用于客服、售前和线索分级场景。
