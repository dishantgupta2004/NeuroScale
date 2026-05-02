"""Document upload + list schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    file_size_bytes: int
    chunk_count: int
    status: str
    error: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class IngestStatsResponse(BaseModel):
    company_id: str
    document_count: int
    chunk_count: int
    vector_count: int