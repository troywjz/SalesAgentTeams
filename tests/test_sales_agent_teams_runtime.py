from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from agentteams.local_runner import LocalSalesTeam
from sales_agent_teams.contracts import AgentRequest, HeatmapRequest
from sales_agent_teams.evaluation_service import generate_3d_heatmap


def test_local_team_runs_all_six_business_workers() -> None:
    result = asyncio.run(
        LocalSalesTeam().run_turn(
            "我想了解适合零基础的课程",
            conversation_id="test-conversation",
            turn_id="test-turn",
        )
    )
    worker_ids = [item["worker_id"] for item in result["trace"]]
    assert worker_ids == [
        "memory_worker",
        "intent_worker",
        "sop_worker",
        "knowledge_worker",
        "conversation_worker",
        "safety_worker",
        "memory_worker",
    ]
    assert result["final_reply"]


def test_agent_request_rejects_empty_message() -> None:
    try:
        AgentRequest(
            task_id="task",
            conversation_id="conversation",
            turn_id="turn",
            message="",
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("空消息必须被拒绝")


def test_heatmap_is_generated_from_real_score_rows(monkeypatch, tmp_path: Path) -> None:
    import sales_agent_teams.paths as paths

    monkeypatch.setattr(paths, "EVALUATION_ROOT", tmp_path)
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    labels = ["信息准确 A", "不违规 C", "解决问题 R", "意向推进 P", "用户反馈 F"]
    with (run_dir / "评分明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["来源", "回复来源", *labels])
        writer.writeheader()
        for turn_id in ("t1", "t2"):
            for source in ("系统销售", "真人销售"):
                writer.writerow(
                    {
                        "来源": turn_id,
                        "回复来源": source,
                        **{label: "1" if source == "系统销售" else "0.8" for label in labels},
                    }
                )

    result = generate_3d_heatmap(HeatmapRequest(run_dir=str(run_dir), source="both"))
    assert Path(result["html_path"]).is_file()
    assert Path(result["manifest_path"]).is_file()
    assert "SalesAgentTeams" in Path(result["html_path"]).read_text(encoding="utf-8")
