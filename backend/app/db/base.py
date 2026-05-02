"""
SQLAlchemy 2.0 declarative base.

Every ORM table inherits from `Base`. Common columns (id, created_at,
updated_at) live on `TimestampedBase` so we don't repeat ourselves.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base. Naming convention helps Alembic auto-generate
    consistent constraint names across migrations."""
    pass


def _uuid_str() -> str:
    """UUIDs as strings — portable across PG / SQLite for tests, and easy
    to log + serialize without converters."""
    return str(uuid.uuid4())


class TimestampedBase(Base):
    """Mixin-style base for tables that need id + timestamps."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )