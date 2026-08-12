---
name: sop-decision
description: 按销售阶段和客户意图给出下一步可执行动作。
---

# SOP Decision Skill

版本：1.1.0

## 目的

把意图和会话状态映射到受控销售阶段、下一步动作和人工接管判断。

## 输入

客户消息、意图结果、当前阶段、允许阶段列表和会话状态。

## 输出

`current_stage`、`next_action`、`should_transfer`、`reason`。

## 触发条件

意图识别后触发；Supervisor 判定简单寒暄或强制转人工时跳过。

## 依赖工具

Sales Agent Bridge MCP 的 `run_sop_agent`、版本化办公技能销售 SOP、`evidence-handoff`。

## 失败处理

阶段无法确定时保留当前阶段并请求补充上下文；涉及交易确认时转人工。

## 安全边界

只能选择清单中的阶段，不执行付款、合同、文件上传或客户外呼，不绕过安全审核。

## 复用价值

可复用于任何阶段化售前、客服升级和客户成功流程。

## 多 Agent 流程关系

承接 Intent Worker，约束 Knowledge 与 Conversation Worker 的检索和回复目标。

## 验证

校验阶段属于允许列表、下一步非空、转人工条件可解释且超时动作可追踪。
