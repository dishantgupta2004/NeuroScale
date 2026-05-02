"""
AgentRun — one row per LangGraph invocation.

This is the audit trail and the polling target. The frontend hits
GET /agent-run/{run_id} and reads the latest status + state snapshot.

Why JSON for `state_snapshot`?
- AgentState is already a dict by design (TypedDict).
- We don't query inside the state — only display it. JSON is right.
- Postgres JSONB indexing exists if we ever want to filter by it.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class AgentRun(TimestampedBase):
    __tablename__ = "agent_runs"

    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    task: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # "running" | "complete" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)

    # Final state dict. Big-ish (~10-50KB) but bounded.
    state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Convenience extracts (denormalized from state_snapshot for fast list views)
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)