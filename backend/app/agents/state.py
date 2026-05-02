"""
Shared state for the multi-agent graph.

LangGraph passes this dict through every node. Each node returns a *partial*
update; LangGraph merges it into the state. The schema is intentionally flat
and JSON-serializable so we can persist runs to PostgreSQL.

Conventions
-----------
- All fields default to None / empty list, so partial updates work cleanly.
- Lists use `Annotated[list, operator.add]` when we want LangGraph to
  *append* across nodes (e.g. citations from multiple retrieval steps).
- Anything we want to inspect from /agent-run polling lives here.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

# Type aliases for clarity
ContentType = Literal["blog", "linkedin_post", "twitter_post", "email", "research_summary"]
ReviewVerdict = Literal["approved", "needs_revision", "rejected"]


class AgentState(TypedDict, total=False):
    """
    The big shared dict. `total=False` lets us return partial updates without
    every key being present.
    """

    # ---------- Inputs (set once at graph entry) ----------
    company_id: str
    run_id: str                       # links back to agent_runs table row
    task: str                         # natural-language goal, e.g. "write a LinkedIn post about X"
    content_type: ContentType
    target_audience: str | None       # optional override; otherwise pulled from RAG

    # ---------- Strategist output ----------
    plan: str | None                  # the approach the writer should follow
    key_points: list[str]             # bulleted points the content must hit
    tone_guide: str | None            # tone description pulled from company brain

    # ---------- Researcher output ----------
    research_context: str | None      # formatted RAG block ready for prompts
    citations: Annotated[list[dict], operator.add]  # accumulated across retrievals

    # ---------- Writer output ----------
    draft: str | None
    revision_count: int               # how many times Writer has run

    # ---------- Reviewer output ----------
    review_verdict: ReviewVerdict | None
    review_feedback: str | None       # what to change if needs_revision

    # ---------- Communicator output (final) ----------
    final_content: str | None
    metadata: dict[str, Any]          # anything else (subject, hashtags, etc.)

    # ---------- Diagnostics ----------
    errors: Annotated[list[str], operator.add]
    node_trace: Annotated[list[str], operator.add]   # ordered list of nodes visited


# Convenience: what an empty starting state looks like.
def initial_state(
    *,
    company_id: str,
    run_id: str,
    task: str,
    content_type: ContentType,
    target_audience: str | None = None,
) -> AgentState:
    return AgentState(
        company_id=company_id,
        run_id=run_id,
        task=task,
        content_type=content_type,
        target_audience=target_audience,
        plan=None,
        key_points=[],
        tone_guide=None,
        research_context=None,
        citations=[],
        draft=None,
        revision_count=0,
        review_verdict=None,
        review_feedback=None,
        final_content=None,
        metadata={},
        errors=[],
        node_trace=[],
    )


# Loop-prevention: hard cap on Writer↔Reviewer revisions
MAX_REVISIONS = 2