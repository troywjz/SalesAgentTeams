"""离线评估、评分和 3D 热力图 MCP 服务。"""

from __future__ import annotations

import argparse
import os
from typing import Any

from sales_agent_teams.contracts import (
    EvaluationRunRequest,
    EvaluationScoreRequest,
    HeatmapRequest,
)
from sales_agent_teams.evaluation_service import (
    generate_3d_heatmap,
    run_offline_evaluation,
    score_offline_evaluation,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment,misc]


def build_server() -> Any:
    if FastMCP is None:
        raise RuntimeError("缺少 MCP SDK，请先安装 requirements.txt。")
    server = FastMCP(
        "sales-evaluation-insights",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
    )

    @server.tool(name="run_offline_evaluation")
    async def run_offline_evaluation_tool(request: dict[str, Any]) -> dict[str, Any]:
        """回放公开数据集，并生成原始结果、技术明细和盲评模板。"""
        return await run_offline_evaluation(EvaluationRunRequest.model_validate(request))

    @server.tool(name="score_offline_evaluation")
    async def score_offline_evaluation_tool(request: dict[str, Any]) -> dict[str, Any]:
        """将已完成的盲评结果转换为评分明细和评估报告。"""
        return await score_offline_evaluation(EvaluationScoreRequest.model_validate(request))

    @server.tool(name="generate_3d_heatmap")
    def generate_3d_heatmap_tool(request: dict[str, Any]) -> dict[str, Any]:
        """从真实评分明细生成自包含 3D HTML 热力图和 JSON 清单。"""
        return generate_3d_heatmap(HeatmapRequest.model_validate(request))

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="SalesAgentTeams evaluation MCP")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    build_server().run(transport=args.transport)


if __name__ == "__main__":
    main()
