"""SSE 传输层工具。

心跳为什么必须做：Nginx / 云厂商 LB 默认 60s 无数据就断连。
真实 Agent 在等 LLM 首 token 时可能空转 10 秒以上，没有心跳会被判死。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.agent.events import PING

# 契约固定值：contracts/sse-events.md 第 2 节
HEARTBEAT_SECONDS = 15.0

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # 关键：不加这个，Nginx 会把事件攒批，流式退化成"等几秒一次性蹦出来"
    "X-Accel-Buffering": "no",
}


async def with_heartbeat(
    source: AsyncIterator[str],
    interval: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """在事件流空闲超过 interval 秒时插入一条 `: ping` 注释行。"""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield PING
                continue
            if item is None:
                break
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
