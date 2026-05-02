"""
Email schemas.

Two-step flow:
  1. POST /send-email      -> creates a pending_approval row, returns id
  2. POST /approve-email   -> flips to approved, queues SES send
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class DraftEmailRequest(BaseModel):
    """Generate + save a draft. Either provide explicit body or ask the agent."""
    to_address: EmailStr
    subject: str | None = Field(default=None, max_length=998)
    body: str | None = Field(default=None, max_length=50000)
    # If body is None, we generate one from this prompt via the agent graph.
    generation_task: str | None = Field(default=None, max_length=2000)


class EmailResponse(BaseModel):
    id: str
    to_address: str
    from_address: str
    subject: str
    body: str
    status: Literal["pending_approval", "approved", "rejected", "sent", "send_failed"]
    ses_message_id: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApproveEmailRequest(BaseModel):
    email_id: str
    approve: bool = True   # set False to reject without sending


class EmailListResponse(BaseModel):
    emails: list[EmailResponse]
    total: int