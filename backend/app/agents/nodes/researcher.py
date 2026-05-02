"""
Researcher node.

Takes the plan from Strategist and pulls topic-specific RAG context, then
synthesizes a research brief the Writer can lean on.

Uses TaskType.FAST_GENERATION -> Groq llama-3.1-8b-instant.
The researcher's job is summarization, not deep reasoning, so the small/fast
model is the right pick.
"""
from __future__ import annotations

from loguru import logger

from app.agents.nodes._shared import load_prompt, trace
from app.agents.state import AgentState
from app.llm_router import Message, TaskType, router
from app.rag import retriever


async def researcher_node(state: AgentState) -> dict:
    company_id = state["company_id"]
    task = state["task"]
    plan = state.get("plan") or task
    key_points = state.get("key_points") or []

    # 1. Build a focused retrieval query from the plan + key points.
    #    Concatenating them gives the embedder more semantic surface area
    #    than just the original task string.
    query = f"{plan}\n\n" + "\n".join(f"- {kp}" for kp in key_points)

    rag = await retriever.retrieve(
        company_id=company_id,
        query=query,
        top_k=8,                # researcher gets more context than strategist
        strategy="mmr",         # diversity matters for evidence
    )

    # 2. Synthesize the brief.
    prompt = load_prompt("researcher").format(
        company_id=company_id,
        plan=plan,
        key_points="\n".join(f"- {kp}" for kp in key_points) or "(none provided)",
        retrieved_context=rag.formatted_text,
    )

    try:
        resp = await router.complete(
            messages=[
                Message("system", "You are a meticulous research assistant. Cite evidence inline."),
                Message("user", prompt),
            ],
            task_type=TaskType.FAST_GENERATION,
            temperature=0.3,    # facts, not creativity
            max_tokens=900,
        )
        brief = resp.text.strip()
    except Exception as e:
        logger.exception(f"Researcher failed: {e}")
        return {
            **trace("researcher"),
            "errors": [f"researcher: {e}"],
            # Fallback: give Writer the raw RAG so the chain can still produce something.
            "research_context": rag.formatted_text,
            "citations": rag.citations,
        }

    return {
        **trace("researcher"),
        "research_context": brief,
        "citations": rag.citations,
    }