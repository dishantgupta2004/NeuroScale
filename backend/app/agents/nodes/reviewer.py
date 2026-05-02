"""
Reviewer node.

The Reviewer sees the full draft + research brief + company tone — i.e.
potentially sensitive aggregated company knowledge. So we route this one
through TaskType.SENSITIVE -> Ollama (local model).

Output is structured: {verdict, feedback, issues}.
"""
from __future__ import annotations

from loguru import logger

from app.agents.nodes._shared import load_prompt, parse_json_response, trace
from app.agents.state import AgentState
from app.llm_router import Message, TaskType, router


_VALID_VERDICTS = {"approved", "needs_revision", "rejected"}


async def reviewer_node(state: AgentState) -> dict:
    company_id = state["company_id"]
    content_type = state["content_type"]
    plan = state.get("plan") or "(none)"
    key_points = state.get("key_points") or []
    tone_guide = state.get("tone_guide") or "(none)"
    research_brief = state.get("research_context") or "(none)"
    draft = state.get("draft")

    if not draft:
        # Nothing to review. Skip ahead.
        return {
            **trace("reviewer"),
            "review_verdict": "rejected",
            "review_feedback": "No draft to review",
            "errors": ["reviewer: empty draft"],
        }

    prompt = load_prompt("reviewer").format(
        company_id=company_id,
        content_type=content_type,
        plan=plan,
        key_points="\n".join(f"- {kp}" for kp in key_points) or "(none)",
        tone_guide=tone_guide,
        research_brief=research_brief,
        draft=draft,
    )

    try:
        resp = await router.complete(
            messages=[
                Message(
                    "system",
                    "You are a critical editor. Be honest about weaknesses. Return only valid JSON.",
                ),
                Message("user", prompt),
            ],
            task_type=TaskType.SENSITIVE,    # -> Ollama first
            temperature=0.2,                  # consistency matters
            max_tokens=600,
        )
        parsed = parse_json_response(resp.text)
    except Exception as e:
        logger.exception(f"Reviewer failed: {e}")
        # If the reviewer breaks, default to "approved" to avoid blocking
        # the pipeline forever. The user still has the human-approval gate
        # before anything actually gets sent.
        return {
            **trace("reviewer"),
            "review_verdict": "approved",
            "review_feedback": "Reviewer agent failed; auto-approving (human review still required before send)",
            "errors": [f"reviewer: {e}"],
        }

    verdict = parsed.get("verdict", "approved")
    if verdict not in _VALID_VERDICTS:
        logger.warning(f"Reviewer returned unknown verdict: {verdict}; defaulting to approved")
        verdict = "approved"

    return {
        **trace("reviewer"),
        "review_verdict": verdict,
        "review_feedback": parsed.get("feedback", ""),
    }