"""
Async SQLAlchemy engine + session factory.

Pattern: one engine per process, one session per request. The session is
created on demand by the FastAPI dependency `get_db()` and closed when the
request finishes.

Why expire_on_commit=False?
- After commit, attribute access on ORM objects would trigger a refresh
  (another query). In an async app that's a footgun. We commit explicitly
  and use the objects as plain Python until end of request.
"""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# echo=True spams logs in dev. Toggle via env if you want SQL traces.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=10,
    max_overflow=10,
    pool_pre_ping=True,   # recover from stale RDS connections
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency. Use as:
        async def my_route(db: AsyncSession = Depends(get_db)): ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise