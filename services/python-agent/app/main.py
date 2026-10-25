"""CodeAtlas Agent 服务入口。

启动：
    cd services/python-agent
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

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
async def _log_mode() -> None:
    logging.getLogger(__name__).info(
        "startup | mode=%s | model=%s | llm_key=%s",
        "mock" if settings.mock_agent else "live",
        # 打 agent_model 而不是 llm_model：后者是硅基流动的 DeepSeek 模型名，
        # 和 Agent 实际调用的模型无关，打成那个会让人误以为配错了模型。
        settings.agent_model,
        "set" if settings.has_llm_key else "MISSING",
    )
