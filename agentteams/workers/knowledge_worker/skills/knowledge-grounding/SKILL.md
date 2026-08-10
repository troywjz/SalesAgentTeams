---
name: knowledge-grounding
description: 从授权知识快照中检索销售事实并返回可引用证据。
---

# Knowledge Grounding Skill

版本：1.0.0

## 输入

客户消息、意图、销售阶段、授权知识引用和检索限制。

## 输出

返回匹配方案、事实、政策提示、缺失信息和 `knowledge_sufficiency`。

## 触发与边界

在 SOP 决策后触发。只读取授权知识源，不读取风控规则之外的私有文件，不把推测写成产品事实。

## 失败处理

知识源不可用或证据不足时返回 `insufficient`，让 Conversation Worker 采用澄清式回复；不得自行补全价格、权益或承诺。

## 验证与复用

验证每条事实有来源或明确标记缺失；可复用于商品咨询、售前问答和内部知识助手。
