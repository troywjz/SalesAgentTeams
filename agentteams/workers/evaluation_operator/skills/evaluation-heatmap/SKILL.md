---
name: evaluation-heatmap
description: 根据真实评分明细生成可交互的 3D 指标热力图。
---

# Evaluation Heatmap Skill

版本：1.0.0

只接受已生成的 `评分明细.csv`，调用 `generate_3d_heatmap` 输出自包含 HTML 和 JSON 清单。缺少评分或指标越界时失败，不补造数据。
