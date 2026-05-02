"""
Writer node.

Produces the actual draft. Runs on first pass and on revisions — the only
difference is whether `review_feedback` is present in state.

Uses TaskType.FAST_GENERATION -> Groq llama-3.1-8b-instant.
"""
from __future__ import annotations

from loguru import logger

from app.agents.nodes._shared import format_rules_for, load_prompt, trace
from app.agents.state import AgentState
from app.llm_router import Message, TaskType, router


async def writer_node(state: AgentState) -> dict:
    company_id = state["company_id"]
    content_type = state["content_type"]
    plan = state.get("plan") or state["task"]
    key_points = state.get("key_points") or []
    tone_guide = state.get("tone_guide") or "Professional and clear"
    research_brief = state.get("research_context") or "(no research context available)"
    revision_feedback = state.get("review_feedback")
    revision_count = state.get("revision_count", 0)

    is_revision = bool(revision_feedback)
    if is_revision:
        logger.info(f"Writer running revision pass #{revision_count + 1}")

    prompt = load_prompt("writer").format(
        company_id=company_id,
        content_type=content_type,
        plan=plan,
        key_points="\n".join(f"- {kp}" for kp in key_points) or "(none specified)",
        tone_guide=tone_guide,
        research_brief=research_brief,
        revision_feedback=revision_feedback or "(none — this is the first draft)",
        format_rules=format_rules_for(content_type),
    )

    try:
        resp = await router.complete(
            messages=[
                Message(
                    "system",
                    "You are a skilled writer. Match the requested tone exactly and produce only the final content.",
                ),
                Message("user", prompt),
            ],
            task_type=TaskType.FAST_GENERATION,
            temperature=0.7,    # some creative latitude
            max_tokens=1500,
        )
        draft = resp.text.strip()
    except Exception as e:
        logger.exception(f"Writer failed: {e}")
        return {
            **trace("writer"),
            "errors": [f"writer: {e}"],
            "draft": state.get("draft"),  # keep prior draft if any
            "revision_count": revision_count + 1,
        }

    return {
        **trace("writer"),
        "draft": draft,
        "revision_count": revision_count + 1,
        # Clear feedback so the next reviewer pass evaluates fresh.
        "review_feedback": None,
    }