from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder


class WebSocketConnectionManager:
    """Windows Demo 的单进程 WebSocket 连接管理器。"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._connections.clear()

    async def connect(self, websocket: WebSocket, viewer: str) -> None:
        await websocket.accept()
        self._connections[viewer].add(websocket)

    def disconnect(self, websocket: WebSocket, viewer: str) -> None:
        self._connections[viewer].discard(websocket)

    async def send_json(self, websocket: WebSocket, payload: dict[str, Any]) -> None:
        await websocket.send_json(jsonable_encoder(payload))

    async def broadcast(self, viewer: str, payload: dict[str, Any]) -> None:
        await self._broadcast_local(viewer, jsonable_encoder(payload))

    async def broadcast_all(self, payload: dict[str, Any]) -> None:
        encoded = jsonable_encoder(payload)
        for viewer in list(self._connections):
            await self._broadcast_local(viewer, encoded)

    async def _broadcast_local(self, viewer: str, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self._connections.get(viewer, set())):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket, viewer)


realtime_manager = WebSocketConnectionManager()
