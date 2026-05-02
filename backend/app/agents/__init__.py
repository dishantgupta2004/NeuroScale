"""
Agents package — public API.

Usage from services / routes:

    from app.agents import agent_graph

    final_state = await agent_graph.run(
        company_id="acme",
        run_id="run-123",
        task="Write a LinkedIn post about our new pricing model",
        content_type="linkedin_post",
    )
    print(final_state["final_content"])
"""
from app.agents.graph import AgentGraph, agent_graph
from app.agents.state import AgentState, MAX_REVISIONS, initial_state

__all__ = [
    "AgentGraph",
    "AgentState",
    "MAX_REVISIONS",
    "agent_graph",
    "initial_state",
]