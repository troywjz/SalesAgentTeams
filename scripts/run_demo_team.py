"""运行无需外部 API 的六 Worker 销售流程演示。"""

from __future__ import annotations

import asyncio
import json

from agentteams.local_runner import LocalSalesTeam


async def run() -> None:
    result = await LocalSalesTeam().run_turn(
        "我想了解适合零基础的课程，价格大概是多少？",
        conversation_id="public-demo",
        turn_id="demo-turn-001",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
