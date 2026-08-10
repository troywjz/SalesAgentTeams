"""便捷启动离线评估 MCP 服务。"""

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from mcp_servers.evaluation_insights import main


if __name__ == "__main__":
    main()
