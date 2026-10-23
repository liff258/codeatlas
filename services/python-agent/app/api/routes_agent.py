"""Agent 内部接口。仅供 Java 网关调用，不对浏览器暴露。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.events import EventStream
from app.agent.mock_runner import mock_stream
from app.api.deps import verify_internal_token
from app.api.sse import SSE_HEADERS, with_heartbeat
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_token)],
)


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class InternalChatRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=2000)
    session_id: int | None = None
    history: list[HistoryItem] = Field(default_factory=list)


async def _guarded_stream(req: InternalChatRequest) -> AsyncIterator[str]:
    """把 Agent 的执行包一层：任何异常都要转成 error + done。

    为什么必须这样做：前端状态机靠 done 收尾。如果异常直接抛出，
    连接会断在半路，前端会永远停在"正在思考"，演示时非常致命。
    """
    source: AsyncIterator[str] = mock_stream(
        question=req.question,
        session_id=req.session_id,
        history=[h.model_dump() for h in req.history],
        trace_id=req.trace_id,  # 必须沿用上游给的 trace_id，不要自己生成
    )

    try:
        async for chunk in source:
            yield chunk
    except Exception as exc:  # noqa: BLE001 - 兜底，不能让它冒到连接层
        logger.exception("agent stream failed: trace_id=%s", req.trace_id)
        es = EventStream(req.trace_id)
        yield es.error("INTERNAL", f"Agent 执行异常：{exc.__class__.__name__}")
        yield es.done(stop_reason="error")


@router.post("/agent/stream", summary="Agent 流式推理（仅供 Java 调用）")
async def agent_stream(req: InternalChatRequest) -> StreamingResponse:
    return StreamingResponse(
        with_heartbeat(_guarded_stream(req)),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )
