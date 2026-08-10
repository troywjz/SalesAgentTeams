"""将现有离线评估流水线包装成可被 MCP 调用的服务。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.llm import DemoLLMClient, create_llm_client
from evaluation.core.csv_logger import read_csv
from evaluation.core.scoring import score_blind_review
from evaluation.run import run_evaluation

from .contracts import EvaluationRunRequest, EvaluationScoreRequest, HeatmapRequest
from .paths import RESULT_ROOT, resolve_public_path, sha256_file


async def run_offline_evaluation(request: EvaluationRunRequest) -> dict[str, Any]:
    input_path = resolve_public_path(request.dataset_path)
    output_root = resolve_public_path(request.output_dir or RESULT_ROOT, allow_missing=True)
    llm_client = DemoLLMClient(delay_ms=0) if request.model_mode == "demo" else create_llm_client()
    summary = await run_evaluation(
        input_path,
        output_root=output_root,
        llm_client=llm_client,
    )
    result: dict[str, Any] = {
        "run_id": summary.run_id,
        "run_dir": str(summary.run_dir),
        "turns_total": summary.turns_total,
        "turns_succeeded": summary.turns_succeeded,
        "turns_handed_off": summary.turns_handed_off,
        "turns_failed": summary.turns_failed,
        "model_mode": summary.model_mode,
        "input_sha256": sha256_file(input_path),
        "artifacts": {
            "system_results": str(summary.results_path),
            "blind_review": str(summary.blind_review_path),
            "blind_mapping": str(summary.blind_mapping_path),
        },
    }
    if request.review_path:
        score_result = await score_offline_evaluation(
            EvaluationScoreRequest(
                run_dir=str(summary.run_dir),
                review_path=request.review_path,
                output_dir=str(summary.run_dir),
            )
        )
        result["score"] = score_result
    return result


async def score_offline_evaluation(request: EvaluationScoreRequest) -> dict[str, Any]:
    run_dir = resolve_public_path(request.run_dir)
    review_path = resolve_public_path(request.review_path)
    output_dir = resolve_public_path(request.output_dir or run_dir, allow_missing=True)
    summary = score_blind_review(
        run_dir,
        review_path,
        output_dir=output_dir,
    )
    return {
        "run_dir": str(summary.run_dir),
        "review_file": str(summary.review_file),
        "score_detail_path": str(summary.score_detail_path),
        "report_path": str(summary.report_path),
        "turns_total": summary.turns_total,
        "human_score": summary.human_score,
        "system_score": summary.system_score,
        "score_difference": summary.score_difference,
        "technical_failed_turns": summary.technical_failed_turns,
    }


def generate_3d_heatmap(request: HeatmapRequest) -> dict[str, Any]:
    """从真实评分明细生成自包含 Plotly 3D 热力图。"""

    try:
        import plotly.graph_objects as go
    except ImportError as exc:  # pragma: no cover - 由安装检查覆盖
        raise RuntimeError("生成热力图需要安装 plotly。") from exc

    run_dir = resolve_public_path(request.run_dir)
    score_path = run_dir / "评分明细.csv"
    if not score_path.exists():
        raise FileNotFoundError("运行目录缺少评分明细.csv，请先完成盲评评分。")
    columns, rows = read_csv(score_path)
    required = {"来源", "回复来源", "信息准确 A", "不违规 C", "解决问题 R", "意向推进 P", "用户反馈 F"}
    missing = required.difference(columns)
    if missing:
        raise ValueError(f"评分明细缺少字段: {', '.join(sorted(missing))}")

    source_names = {"system": "系统销售", "human": "真人销售"}
    selected = [source_names[request.source]] if request.source != "both" else ["系统销售", "真人销售"]
    metric_names = ["信息准确 A", "不违规 C", "解决问题 R", "意向推进 P", "用户反馈 F"]
    turn_ids = list(dict.fromkeys(str(row["来源"]) for row in rows))
    if not turn_ids:
        raise ValueError("评分明细没有可视化数据。")

    fig = go.Figure()
    manifest_sources: dict[str, Any] = {}
    for index, source in enumerate(selected):
        source_rows = {str(row["来源"]): row for row in rows if row["回复来源"] == source}
        if set(source_rows) != set(turn_ids):
            raise ValueError(f"{source} 的评分明细未覆盖全部对话回合。")
        z_values: list[list[float]] = []
        for metric in metric_names:
            values: list[float] = []
            for turn_id in turn_ids:
                raw = source_rows[turn_id].get(metric, "")
                try:
                    value = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{source}/{turn_id}/{metric} 不是数字。") from exc
                if value < 0 or value > 1:
                    raise ValueError(f"{source}/{turn_id}/{metric} 超出 0～1 范围。")
                values.append(value)
            z_values.append(values)
        colorscale = "Oranges" if source == "系统销售" else "Blues"
        fig.add_trace(
            go.Surface(
                x=turn_ids,
                y=metric_names,
                z=z_values,
                name=source,
                colorscale=colorscale,
                showscale=True,
                opacity=0.92 if len(selected) == 1 else 0.78,
                colorbar={"title": source, "x": 1.02 + index * 0.12},
                hovertemplate="来源=%{x}<br>指标=%{y}<br>评分=%{z:.2f}<extra>" + source + "</extra>",
            )
        )
        manifest_sources[source] = {metric: z_values[i] for i, metric in enumerate(metric_names)}

    fig.update_layout(
        title="SalesAgentTeams 离线评估 3D 指标热力图",
        template="plotly_white",
        margin={"l": 20, "r": 160, "t": 70, "b": 20},
        scene={
            "xaxis_title": "对话回合",
            "yaxis_title": "评估指标",
            "zaxis_title": "评分（0～1）",
            "zaxis": {"range": [0, 1]},
        },
        legend={"title": "回复来源"},
    )
    output_dir = resolve_public_path(request.output_dir or run_dir, allow_missing=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "3d_heatmap.html"
    json_path = output_dir / "3d_heatmap.json"
    fig.write_html(html_path, include_plotlyjs=True, full_html=True)
    manifest = {
        "run_dir": str(run_dir),
        "source": request.source,
        "turn_ids": turn_ids,
        "metrics": metric_names,
        "sources": manifest_sources,
        "html": str(html_path),
    }
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "html_path": str(html_path),
        "manifest_path": str(json_path),
        "source": request.source,
        "turns_total": len(turn_ids),
        "metrics": metric_names,
    }
