"""Query + content generation + agent run schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- /query ----------
class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    strategy: Literal["similarity", "mmr"] = "mmr"


class QueryResponse(BaseModel):
    answer: str
    citations: list[dict]


# ---------- /generate-content + /agent-run ----------
ContentTypeLiteral = Literal[
    "blog", "linkedin_post", "twitter_post", "email", "research_summary"
]


class GenerateContentRequest(BaseModel):
    task: str = Field(min_length=5, max_length=2000)
    content_type: ContentTypeLiteral
    target_audience: str | None = Field(default=None, max_length=500)


class AgentRunResponse(BaseModel):
    """Returned by /generate-content and /agent-run/{id}."""
    id: str
    status: Literal["running", "complete", "failed"]
    task: str
    content_type: str
    final_content: str | None = None
    review_verdict: str | None = None
    error: str | None = None
    state_snapshot: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]
    total: int