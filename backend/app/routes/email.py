"""Email routes with explicit human approval gate."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import (
    ApproveEmailRequest,
    CurrentUser,
    DraftEmailRequest,
    EmailListResponse,
    EmailResponse,
)
from app.services import email_service

router = APIRouter(tags=["email"])


@router.post("/send-email", response_model=EmailResponse, status_code=201)
async def draft_email(
    payload: DraftEmailRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailResponse:
    """
    Endpoint name is `/send-email` for spec compatibility, but the email is
    NOT sent here — only drafted. Status will be `pending_approval`. Call
    `/approve-email` to actually send.
    """
    return await email_service.draft(
        db,
        company_id=current.company_id,
        user_id=current.user_id,
        payload=payload,
    )


@router.post("/approve-email", response_model=EmailResponse)
async def approve_email(
    payload: ApproveEmailRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailResponse:
    """
    Approve (or reject) a pending email. On approve, the SES send happens.
    """
    return await email_service.approve_and_send(
        db, company_id=current.company_id, payload=payload
    )


@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailListResponse:
    return await email_service.list_for_company(db, company_id=current.company_id)