"""
EmailLog — every drafted email + its approval state + send result.

Status lifecycle:
    pending_approval  -> approved        -> sent          (happy path)
                      -> rejected                          (user said no)
    pending_approval  -> approved        -> send_failed   (SES error)

We don't actually call SES until status flips to "approved". This is the
human-in-the-loop gate.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class EmailLog(TimestampedBase):
    __tablename__ = "email_logs"

    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )

    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False)  # RFC 5322 limit
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Lifecycle: pending_approval | approved | rejected | sent | send_failed
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_approval", index=True
    )

    # SES message-id when sent successfully
    ses_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)