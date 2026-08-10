import asyncio

from app.realtime import WebSocketConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


def test_local_websocket_broadcast() -> None:
    async def scenario():
        manager = WebSocketConnectionManager()
        socket = FakeWebSocket()
        await manager.connect(socket, "sales")
        await manager.broadcast("sales", {"type": "session_updated"})
        return socket

    socket = asyncio.run(scenario())
    assert socket.accepted is True
    assert socket.messages == [{"type": "session_updated"}]
