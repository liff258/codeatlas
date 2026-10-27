"""CodeAtlas Agent 服务入口。

启动：
    cd services/python-agent
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import FastAPI

from app.api import routes_agent, routes_health
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

app = FastAPI(
    title="CodeAtlas Agent Service",
    version="0.1.0",
    description=(
        "内部服务，仅供 Java 网关调用。"
        "所有接口需要 X-Internal-Token，不对浏览器暴露。"
    ),
    docs_url="/internal/docs",
    openapi_url="/internal/openapi.json",
)

app.include_router(routes_health.router)
app.include_router(routes_agent.router)


@app.on_event("startup")
async def _startup() -> None:
    log = logging.getLogger(__name__)
    log.info(
        "startup | mode=%s | model=%s | llm_key=%s",
        "mock" if settings.mock_agent else "live",
        # 打 agent_model 而不是 llm_model：后者是硅基流动的 DeepSeek 模型名，
        # 和 Agent 实际调用的模型无关，打成那个会让人误以为配错了模型。
        settings.agent_model,
        "set" if settings.has_llm_key else "MISSING",
    )

    if not settings.agent_warmup or settings.mock_agent:
        return

    # 预热三个本地模型：BM25 索引(约 2s) + embedding(约 8s) + rerank(约 5s)。
    #
    # 不预热的话，这些代价全部落在「第一个提问」上——冷启动实测 40~60 秒，
    # 而用户对第一次使用的印象最敏感。挪到启动时做，第一个问题就和热态一样快。
    #
    # 代价是启动慢约 15 秒，所以 Docker healthcheck 的 start_period 要 ≥ 30s；
    # 开发时 --reload 每次改代码都会重跑一遍，可以设 AGENT_WARMUP=false 关掉。
    started = time.monotonic()
    try:
        from app.rag.rerank import get_reranker
        from app.rag.retrieve import get_retriever

        # 两个都是同步阻塞的，必须放线程里，否则会卡住事件循环
        await asyncio.to_thread(get_retriever)
        await asyncio.to_thread(get_reranker)
        log.info("warmup done in %.1fs", time.monotonic() - started)
    except Exception as e:  # noqa: BLE001
        # 预热失败不影响功能，只是第一个请求会慢——不能因为预热失败让服务起不来
        log.warning("warmup failed in %.1fs（功能不受影响，首个请求会慢）: %s",
                    time.monotonic() - started, e)
