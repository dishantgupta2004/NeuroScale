"""
Document table.

We store metadata only — the raw file lives in S3, the searchable chunks
live in FAISS. This row is the join key between them: doc_id + company_id
appears in chunk metadata so retrieval can map results back to a source.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class Document(TimestampedBase):
    __tablename__ = "documents"

    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")

    # Counts populated after successful ingest
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ingest status: "pending" | "ingesting" | "ready" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)