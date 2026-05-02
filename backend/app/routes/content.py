"""Content generation + agent run routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import (
    AgentRunListResponse,
    AgentRunResponse,
    CurrentUser,
    GenerateContentRequest,
)
from app.services import agent_service

router = APIRouter(tags=["content"])


@router.post(
    "/generate-content", response_model=AgentRunResponse, status_code=202
)
async def generate_content(
    payload: GenerateContentRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    """
    Trigger the multi-agent graph. Returns the AgentRun record once the
    graph completes (synchronous in MVP). Status will be `complete` or
    `failed`. The `state_snapshot` field contains the full agent state
    for debugging.
    """
    return await agent_service.generate_content(
        db,
        company_id=current.company_id,
        user_id=current.user_id,
        payload=payload,
    )


@router.get("/agent-run/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    return await agent_service.get_run(
        db, company_id=current.company_id, run_id=run_id
    )


@router.get("/agent-run", response_model=AgentRunListResponse)
async def list_agent_runs(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunListResponse:
    return await agent_service.list_runs(db, company_id=current.company_id)