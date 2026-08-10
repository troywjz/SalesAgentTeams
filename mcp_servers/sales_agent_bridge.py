"""六个业务 Worker 的 MCP 适配服务。

本服务不复制或重写原 Agent；它只把原项目 Agent 的结构化能力暴露给
AgentTeams Worker。日志必须写到 stderr，避免污染 stdio MCP 协议流。
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from app.llm import create_llm_client

from sales_agent_teams.bridge import SalesAgentBridge
from sales_agent_teams.contracts import AgentRequest

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - 启动检查会提供更清晰的错误
    FastMCP = None  # type: ignore[assignment,misc]


def build_server() -> Any:
    if FastMCP is None:
        raise RuntimeError("缺少 MCP SDK，请先安装 requirements.txt。")
    server = FastMCP(
        "sales-agent-bridge",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
    )
    bridge = SalesAgentBridge(create_llm_client())

    def register(worker_id: str, tool_name: str) -> None:
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            parsed = AgentRequest.model_validate(request)
            response = await bridge.run(worker_id, parsed)
            return response.model_dump(mode="json")

        handler.__name__ = tool_name
        handler.__doc__ = f"调用 {worker_id} 对应的业务 Agent。"
        server.tool()(handler)

    register("intent_worker", "run_intent_agent")
    register("sop_worker", "run_sop_agent")
    register("knowledge_worker", "run_knowledge_agent")
    register("conversation_worker", "run_conversation_agent")
    register("safety_worker", "run_safety_agent")
    register("memory_worker", "run_memory_agent")
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="SalesAgentTeams Agent Bridge MCP")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    build_server().run(transport=args.transport)


if __name__ == "__main__":
    main()
