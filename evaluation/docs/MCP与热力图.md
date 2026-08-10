# 评估 MCP 与 3D 热力图

## 本地调用

在项目根目录执行：

```powershell
python -m mcp_servers.evaluation_insights --transport stdio
```

也可以直接使用本地兼容运行器：

```powershell
python scripts/run_demo_team.py
```

## MCP 工具

- `run_offline_evaluation`：使用 `evaluation/datasets/demo_cases.csv` 回放销售流程，生成系统回复和盲评模板。
- `score_offline_evaluation`：读取人工完成的盲评表，生成 `评分明细.csv` 和 `评估报告.csv`。
- `generate_3d_heatmap`：从真实评分明细生成自包含 `3d_heatmap.html` 和 `3d_heatmap.json`。

MCP 服务只允许访问项目 `evaluation/` 目录，不接受私有聊天记录、`.env` 或路径穿越。没有人工评分时不会自动生成分数。
