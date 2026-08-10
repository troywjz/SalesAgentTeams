"""便捷启动销售 Agent Bridge MCP 服务。"""

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from mcp_servers.sales_agent_bridge import main


if __name__ == "__main__":
    main()
