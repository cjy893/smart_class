import asyncio
import json
import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class SseManager:
    """SSE 推送实时数据给 Dashboard。"""

    def __init__(self):
        self._clients: list[asyncio.Queue] = []

    async def register(self, request: Request) -> StreamingResponse:
        """注册 SSE 客户端连接。"""
        queue: asyncio.Queue = asyncio.Queue()
        self._clients.append(queue)

        async def event_stream():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"data: {json.dumps(data)}\n\n"
                    except asyncio.TimeoutError:
                        yield "data: {\"type\":\"ping\"}\n\n"
            finally:
                self._clients.remove(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def broadcast(self, data: dict) -> None:
        """向所有客户端推送。"""
        for q in self._clients:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass
