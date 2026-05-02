"""
Company = tenant. Everything else is scoped under company_id.
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class Company(TimestampedBase):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Cached company profile, extracted by the Strategist after first ingest.
    # Stored here (not derived on every call) so agents have it in O(1).
    tone_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated