"""
ContentOutput — generated content (blog, social post, etc).

Separate from agent_runs because:
  - One run produces one output, but we may regenerate (new run, new output).
  - The frontend wants a "library" view of content, not a list of runs.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class ContentOutput(TimestampedBase):
    __tablename__ = "content_outputs"

    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )

    content_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)