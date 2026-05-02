"""Document routes: upload, list, delete, stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import CurrentUser
from app.models.document import (
    DocumentListResponse,
    DocumentResponse,
    IngestStatsResponse,
)
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_doc(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    content = await file.read()
    return await document_service.upload(
        db,
        company_id=current.company_id,
        user_id=current.user_id,
        filename=file.filename or "untitled",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    return await document_service.list_for_company(db, company_id=current.company_id)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await document_service.delete(
        db, company_id=current.company_id, document_id=document_id
    )


@router.get("/stats", response_model=IngestStatsResponse)
async def stats(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IngestStatsResponse:
    return await document_service.stats(db, company_id=current.company_id)