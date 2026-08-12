"""端到端集成检查：启动应用后逐链路测试主要 API。"""

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E") != "1",
    reason="Set RUN_E2E=1 after starting the PostgreSQL-backed demo server.",
)


settings = get_settings()
BASE = os.getenv(
    "E2E_BASE_URL",
    f"http://127.0.0.1:{settings.app_port}",
)
T = float(os.getenv("E2E_TIMEOUT_SECONDS", "180"))

# httpx 0.28 默认 transport 可能走系统代理，需要显式指定，避免本地回环请求被代理干扰。
_client = httpx.Client(transport=httpx.HTTPTransport(), timeout=T)
_sales_token = ""


def get(path: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {_sales_token}"} if _sales_token else None
    return _client.get(f"{BASE}{path}", headers=headers)


def post(path: str, data: dict) -> httpx.Response:
    headers = {"Authorization": f"Bearer {_sales_token}"} if _sales_token else None
    return _client.post(f"{BASE}{path}", json=data, headers=headers)


def check(label: str, resp: httpx.Response) -> bool:
    if resp.status_code != 200:
        print(f"  FAIL [{label}]: HTTP {resp.status_code} - {resp.text[:200]}")
        return False
    print(f"  OK [{label}]")
    return True


def state_profile(state: dict) -> dict:
    return state.get("customer_profile") or state.get("profile") or {}


def state_memory(state: dict) -> str:
    return str(state.get("history_summary") or state.get("memory") or "")


def main() -> None:
    global _sales_token
    errors: list[str] = []

    print("=== Test 1: Health ===")
    r = get("/health")
    if not check("health", r):
        errors.append("health")
        _exit(errors)
    print(f"  status={r.json()['status']}")

    print("\n=== Test 2: List sessions ===")
    r = _client.post(
        f"{BASE}/api/chat/sales/login",
        json={"email": "wangjie@salesagent.com", "password": "123456"},
    )
    if not check("sales-login", r):
        errors.append("sales-login")
        _exit(errors)
    _sales_token = r.json()["access_token"]

    print("\n=== Test 3: List sessions ===")
    r = get("/api/chat/sessions")
    if not check("sessions", r):
        errors.append("sessions")
        _exit(errors)
    print(f"  count={len(r.json()['sessions'])}")

    print("\n=== Test 4: First message ===")
    r = post("/api/chat", {"message": "你好，我想了解一下你们的课程"})
    if not check("chat", r):
        errors.append("chat-first")
        _exit(errors)
    d = r.json()
    sid = d["session_id"]
    print(f"  session_id={sid}")
    print(f"  reply={d['reply'][:100]}")
    print(f"  stage={d['state']['current_stage']}")
    print(f"  transfer={d['state']['transfer_flag']}")
    print(f"  runs={len(d['agent_runs'])}")
    for run in d["agent_runs"]:
        print(f"    - {run['agent_name']} OK={run['success']}")

    print("\n=== Test 5: Continue conversation ===")
    r = post(
        "/api/chat",
        {"message": "我想系统学 Excel 函数和报表，大概多少钱", "session_id": sid},
    )
    if not check("chat-continue", r):
        errors.append("chat-continue")
        _exit(errors)
    d = r.json()
    profile = state_profile(d["state"])
    memory = state_memory(d["state"])
    print(f"  reply={d['reply'][:150]}")
    print(f"  stage={d['state']['current_stage']}")
    print(f"  profile.goal={profile.get('learning_goal', '')}")
    print(f"  profile.intent={profile.get('purchase_intent', '')}")
    print(f"  memory_len={len(memory)}")

    print("\n=== Test 6: Session detail ===")
    r = get(f"/api/chat/sales/sessions/{sid}")
    if not check("detail", r):
        errors.append("detail")
        _exit(errors)
    d = r.json()["session"]
    print(f"  messages={len(d['messages'])}")
    print(f"  agent_runs={len(d['agent_runs'])}")
    print(f"  state.stage={d['state']['current_stage']}")

    print("\n=== Test 7: Set handover ===")
    r = post(
        "/api/chat/sales/handover",
        {"session_id": sid, "enabled": True, "reason": "客户要求人工"},
    )
    if not check("handover-on", r):
        errors.append("handover-on")
        _exit(errors)
    d = r.json()
    print(f"  transfer_flag={d['state']['transfer_flag']}")
    print(f"  transfer_reason={d['state']['transfer_reason']}")

    print("\n=== Test 8: Message while handover ===")
    r = post("/api/chat", {"message": "你好", "session_id": sid})
    if not check("chat-handover", r):
        errors.append("chat-handover")
        _exit(errors)
    d = r.json()
    print(f"  reply={repr(d['reply'][:50])}")
    print(f"  transfer_flag={d['state']['transfer_flag']}")

    print("\n=== Test 9: Cancel handover ===")
    r = post("/api/chat/sales/handover", {"session_id": sid, "enabled": False})
    if not check("handover-off", r):
        errors.append("handover-off")
        _exit(errors)
    d = r.json()
    print(f"  transfer_flag={d['state']['transfer_flag']}")

    print("\n=== Test 10: Reset session ===")
    r = post("/api/chat/reset", {"session_id": sid})
    if not check("reset", r):
        errors.append("reset")
        _exit(errors)
    d = r.json()
    print(f"  stage={d['state']['current_stage']}")
    print(f"  memory_len={len(state_memory(d['state']))}")

    print("\n=== Test 11: Stream message ===")
    final_reply = ""
    stream_client: httpx.Client | None = None
    try:
        stream_client = httpx.Client(transport=httpx.HTTPTransport(), timeout=T)
        with stream_client.stream(
            "POST",
            f"{BASE}/api/chat/stream",
            json={"message": "你好"},
            headers={"Authorization": f"Bearer {_sales_token}"},
        ) as r:
            for line in r.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["type"] == "node_complete":
                    print(f"  node: {event['node']} -> {event.get('next_node', '?')}")
                elif event["type"] == "final":
                    final_reply = event.get("reply", "")
                    print(f"  final_reply={final_reply[:100]}")
                    print(f"  agent_runs={len(event.get('agent_runs', []))}")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        errors.append("stream")
    finally:
        if stream_client is not None:
            stream_client.close()

    if not final_reply:
        errors.append("stream-no-reply")
        print("  FAIL: no final reply in stream")

    _exit(errors)


def _exit(errors: list[str]) -> None:
    print(f"\n{'=' * 50}")
    if errors:
        print(f"FAILED: {errors}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
