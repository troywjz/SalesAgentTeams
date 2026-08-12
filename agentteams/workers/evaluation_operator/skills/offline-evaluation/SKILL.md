---
name: offline-evaluation
description: 调用评估 MCP 生成可审计的离线回放和评分产物。
---

# Offline Evaluation Skill

版本：1.1.0

## 目的

把授权评测数据转换为可复现的回放结果、盲评模板和汇总报告。

## 输入

评测 CSV 路径、运行模式、并发限制，以及可选的真实人工评分文件。

## 输出

回放记录、盲评模板、评分明细、汇总统计和文件清单。

## 触发条件

发布前验证或获得授权的离线评估任务触发；本次比赛材料只引用既有盲评结论，不重跑历史盲评。

## 依赖工具

Evaluation Insights MCP 的 `run_offline_evaluation` 与 `score_offline_evaluation`。

## 失败处理

缺少人工评分时只输出模板与运行证据；字段、权限或数据错误时失败，不补造分数。

## 安全边界

只访问 `evaluation/` 白名单目录；原始聊天须获授权并脱敏；结果不能表述为转化率证明。

## 复用价值

可复用于其他 Agent 的回归集、盲评和版本对比。

## 多 Agent 流程关系

由独立 Evaluation Operator 调用，不介入在线客户回复，也不覆盖 Safety 结论。

## 验证

校验输入摘要、行数、随机映射、评分范围、产物哈希和人工评分缺失时的失败行为。
