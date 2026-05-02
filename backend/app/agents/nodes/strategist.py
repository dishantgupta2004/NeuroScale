"""
Strategist node.

First node in the graph. Sets the plan + tone + key points by combining:
  - The user's task
  - Company brain context (tone, audience, prior content)

Uses TaskType.REASONING -> Groq llama-3.3-70b-versatile.
"""
from __future__ import annotations

from loguru import logger

from app.agents.nodes._shared import load_prompt, parse_json_response, trace
from app.agents.state import AgentState
from app.llm_router import Message, TaskType, router
from app.rag import retriever


async def strategist_node(state: AgentState) -> dict:
    """
    Pull company-tone/audience context from RAG, then ask the reasoning model
    to produce a plan. Returns a partial state update.
    """
    company_id = state["company_id"]
    task = state["task"]
    content_type = state["content_type"]
    target_audience = state.get("target_audience") or "(infer from company brain)"

    # 1. RAG: pull tone-shaping content (vision, about, past posts).
    company_ctx = await retriever.retrieve(
        company_id=company_id,
        query=f"company tone, voice, target audience, brand identity for {content_type}",
        top_k=5,
        strategy="mmr",
    )

    # 2. Build prompt + call reasoning model.
    prompt = load_prompt("strategist").format(
        company_id=company_id,
        company_context=company_ctx.formatted_text,
        task=task,
        content_type=content_type,
        target_audience=target_audience,
    )

    try:
        resp = await router.complete(
            messages=[
                Message("system", "You are a precise content strategist. Return only valid JSON."),
                Message("user", prompt),
            ],
            task_type=TaskType.REASONING,
            temperature=0.4,   # plans should be focused, not creative
            max_tokens=800,
        )
        parsed = parse_json_response(resp.text)
    except Exception as e:
        logger.exception(f"Strategist failed: {e}")
        return {
            **trace("strategist"),
            "errors": [f"strategist: {e}"],
            # Provide minimal fallback so the graph can continue.
            "plan": f"Direct approach: {task}",
            "key_points": [task],
            "tone_guide": "Professional and clear",
            "citations": company_ctx.citations,
        }

    return {
        **trace("strategist"),
        "plan": parsed.get("plan"),
        "key_points": parsed.get("key_points", []),
        "tone_guide": parsed.get("tone_guide"),
        "citations": company_ctx.citations,
    }