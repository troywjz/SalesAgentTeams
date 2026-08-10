---
name: offline-evaluation
description: 调用评估 MCP 生成可审计的离线运行和评分产物。
---

# Offline Evaluation Skill

版本：1.0.0

先调用 `run_offline_evaluation`，完成盲评后再调用 `score_offline_evaluation`。未获得人工评分时，只输出盲评模板和运行证据，不输出伪造的分数。
