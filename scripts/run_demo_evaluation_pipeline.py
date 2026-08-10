"""运行公开数据的完整评估产物链路。

脚本中的评分标签是为了验证流水线的演示值，不是正式评估结论；正式评估应由
授权评审人员填写盲评表后再调用同一个 score_offline_evaluation 工具。
"""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from sales_agent_teams.contracts import EvaluationRunRequest, HeatmapRequest, EvaluationScoreRequest
from sales_agent_teams.evaluation_service import (
    generate_3d_heatmap,
    run_offline_evaluation,
    score_offline_evaluation,
)


LABELS = ("信息准确 A", "不违规 C", "解决问题 R", "意向推进 P", "用户反馈 F")


async def main() -> None:
    result = await run_offline_evaluation(
        EvaluationRunRequest(
            dataset_path="evaluation/datasets/demo_cases.csv",
            model_mode="demo",
        )
    )
    review_path = Path(result["artifacts"]["blind_review"])
    with review_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        columns = list(rows[0]) if rows else []
    columns.extend(
        f"{candidate} {label}"
        for candidate in ("候选甲", "候选乙")
        for label in LABELS
        if f"{candidate} {label}" not in columns
    )
    for row in rows:
        for candidate in ("候选甲", "候选乙"):
            for label in LABELS:
                row[f"{candidate} {label}"] = "1"
        # 仅制造可重复的演示差异，正式评分不使用这段规则。
        if row["来源"] == "demo-003":
            row["候选甲 信息准确 A"] = "0"
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    score = await score_offline_evaluation(
        EvaluationScoreRequest(
            run_dir=result["run_dir"],
            review_path=str(review_path),
        )
    )
    heatmap = generate_3d_heatmap(HeatmapRequest(run_dir=result["run_dir"], source="both"))
    print(json.dumps({"run": result, "score": score, "heatmap": heatmap}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
