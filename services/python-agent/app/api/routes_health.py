"""健康检查。Java 网关的 /api/health 会调用它，前端据此显示"服务状态"。

注意：数据库不可用时返回 degraded 而不是 500。
理由：P0 阶段前端只关心"能不能问答"，DB 挂了这个信息通过 status 字段传递，
让调用方自己决定怎么展示，比直接让整个健康检查失败更有用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import verify_internal_token
from app.config import settings
from app.infra.db import engine

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_token)],
)


@router.get("/health", summary="Agent 服务健康检查")
async def health() -> dict[str, str]:
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_status = f"degraded: {exc.__class__.__name__}"

    return {
        "status": "ok",
        "db": db_status,
        "llm": "ok" if settings.has_llm_key else "missing_key",
        "mode": "mock" if settings.mock_agent else "live",
        "model": settings.llm_model,
    }
