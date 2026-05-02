"""Query route: ask a question of the company brain."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models import CurrentUser, QueryRequest, QueryResponse
from app.services import query_service

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    current: CurrentUser = Depends(get_current_user),
) -> QueryResponse:
    return await query_service.answer(
        company_id=current.company_id, payload=payload
    )