"""数据库连接。

约定：
- 只用同步 Session（见 CLAUDE.md 技术栈），不碰 asyncpg
- 表所有权：Python 只写 chunk / chunk_embedding / entity / relation /
  agent_trace / agent_step / eval_case / eval_result
- document.status 允许 Python 更新（Java 只读），其余 Java 表一律不写
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,  # 防止 Postgres 重启后拿到死连接
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
