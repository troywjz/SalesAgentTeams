---
name: evaluation-heatmap
description: 根据真实评分明细生成可交互的 3D 指标热力图。
---

# Evaluation Heatmap Skill

版本：1.1.0

## 目的

把 A/C/R/P/F 评分明细转成可离线查看的交互式 3D 热力图和产物清单。

## 输入

已生成的 `评分明细.csv`、输出目录和可选标题。

## 输出

自包含 HTML 热力图、JSON 清单、指标范围和文件哈希。

## 触发条件

离线评分完成且评分明细通过校验后触发。

## 依赖工具

Evaluation Insights MCP 的 `generate_3d_heatmap`。

## 失败处理

缺少评分、字段不完整、指标越界或输出目录越权时失败，不补造数据。

## 安全边界

只读取 `evaluation/` 白名单目录，不嵌入原始私密对话，不上传第三方服务。

## 复用价值

指标映射可配置，可用于其他 Agent 版本和业务场景的离线对比。

## 多 Agent 流程关系

位于 Evaluation Operator 的离线支线，消费评分产物，不参与在线六 Worker 闭环。

## 验证

校验 A/C/R/P/F 均在 0 到 1、HTML 可离线打开、清单与文件哈希一致。
