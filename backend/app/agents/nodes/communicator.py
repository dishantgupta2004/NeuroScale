"""
Communicator node.

Final node before END. Takes an approved draft, polishes formatting,
extracts metadata (subject lines, hashtags, etc.) so downstream services
(email sender, social poster) have what they need.

Uses TaskType.FAST_GENERATION — this is light formatting work.
"""
from __future__ import annotations

from loguru import logger

from app.agents.nodes._shared import format_rules_for, load_prompt, parse_json_response, trace
from app.agents.state import AgentState
from app.llm_router import Message, TaskType, router


async def communicator_node(state: AgentState) -> dict:
    company_id = state["company_id"]
    content_type = state["content_type"]
    draft = state.get("draft")

    if not draft:
        return {
            **trace("communicator"),
            "final_content": None,
            "errors": ["communicator: no draft to finalize"],
        }

    prompt = load_prompt("communicator").format(
        company_id=company_id,
        content_type=content_type,
        draft=draft,
        format_rules=format_rules_for(content_type),
    )

    try:
        resp = await router.complete(
            messages=[
                Message(
                    "system",
                    "You are a meticulous editor. Polish without changing substance. Return only valid JSON.",
                ),
                Message("user", prompt),
            ],
            task_type=TaskType.FAST_GENERATION,
            temperature=0.2,
            max_tokens=1500,
        )
        parsed = parse_json_response(resp.text)
    except Exception as e:
        logger.exception(f"Communicator failed: {e}")
        # Fallback: ship the draft as-is rather than failing the whole run.
        return {
            **trace("communicator"),
            "final_content": draft,
            "metadata": {"polished": False},
            "errors": [f"communicator: {e}"],
        }

    return {
        **trace("communicator"),
        "final_content": parsed.get("final_content", draft),
        "metadata": parsed.get("metadata", {}),
    }