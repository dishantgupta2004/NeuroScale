"""
Agent service.

Drives the LangGraph from HTTP-land. Responsible for:
  - Creating the agent_runs row up front (status=running) so polling works.
  - Invoking agent_graph.run(...) and catching all errors.
  - Updating the row with final state, content, verdict.
  - Saving a ContentOutput row for the library view.

Why we create the row before invoking the graph: the agent run can take
30+ seconds (especially if Reviewer triggers a revision). The frontend
needs an id to poll against immediately, not after the run finishes.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import agent_graph
from app.db.tables import AgentRun, ContentOutput
from app.models.content import (
    AgentRunListResponse,
    AgentRunResponse,
    GenerateContentRequest,
)
from app.utils.exceptions import NotFoundError


class AgentService:
    async def generate_content(
        self,
        db: AsyncSession,
        *,
        company_id: str,
        user_id: str,
        payload: GenerateContentRequest,
    ) -> AgentRunResponse:
        # 1. Create persistent run row — gives the frontend something to poll.
        run = AgentRun(
            company_id=company_id,
            triggered_by_user_id=user_id,
            task=payload.task,
            content_type=payload.content_type,
            status="running",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        run_id = run.id
        logger.info(f"Agent run {run_id} started for {company_id}: {payload.task}")

        # 2. Invoke the graph. Exceptions caught and persisted — never bubble.
        try:
            final_state = await agent_graph.run(
                company_id=company_id,
                run_id=run_id,
                task=payload.task,
                content_type=payload.content_type,
                target_audience=payload.target_audience,
            )

            # 3. Re-fetch row for update (separate session lifecycle).
            run.state_snapshot = self._jsonable_state(final_state)
            run.final_content = final_state.get("final_content")
            run.review_verdict = final_state.get("review_verdict")
            run.status = "complete" if final_state.get("final_content") else "failed"
            if not final_state.get("final_content"):
                run.error = (
                    "; ".join(final_state.get("errors", []))
                    or "No final content produced"
                )
            await db.commit()
            await db.refresh(run)

            # 4. If we have content, save it to the library.
            if run.final_content:
                output = ContentOutput(
                    company_id=company_id,
                    agent_run_id=run.id,
                    content_type=payload.content_type,
                    content=run.final_content,
                    extra_metadata=final_state.get("metadata") or {},
                )
                db.add(output)
                await db.commit()

        except Exception as e:
            logger.exception(f"Agent run {run_id} crashed")
            run.status = "failed"
            run.error = str(e)[:5000]
            await db.commit()
            await db.refresh(run)

        return AgentRunResponse.model_validate(run)

    async def get_run(
        self, db: AsyncSession, *, company_id: str, run_id: str
    ) -> AgentRunResponse:
        r = await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id, AgentRun.company_id == company_id
            )
        )
        run = r.scalar_one_or_none()
        if run is None:
            raise NotFoundError("Agent run not found")
        return AgentRunResponse.model_validate(run)

    async def list_runs(
        self, db: AsyncSession, *, company_id: str, limit: int = 50
    ) -> AgentRunListResponse:
        r = await db.execute(
            select(AgentRun)
            .where(AgentRun.company_id == company_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        runs = list(r.scalars())
        return AgentRunListResponse(
            runs=[AgentRunResponse.model_validate(x) for x in runs],
            total=len(runs),
        )

    @staticmethod
    def _jsonable_state(state: dict) -> dict:
        """Strip anything that won't survive JSON serialization. Our state
        is already mostly primitives, but be defensive."""
        out = {}
        for k, v in state.items():
            try:
                import json
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = str(v)
        return out


agent_service = AgentService()