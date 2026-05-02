"""
LangGraph orchestration.

Topology
--------
    START
      │
      ▼
    strategist  ──►  researcher  ──►  writer  ──►  reviewer
                                       ▲             │
                                       └─────────────┤  (needs_revision, count < MAX)
                                                     ▼
                                                 communicator
                                                     │
                                                     ▼
                                                    END

Conditional edges
-----------------
After `reviewer`:
  - verdict == "approved"  -> communicator
  - verdict == "rejected"  -> communicator (ship the draft anyway with a warning)
  - verdict == "needs_revision" AND revision_count < MAX_REVISIONS -> writer
  - verdict == "needs_revision" AND revision_count >= MAX_REVISIONS -> communicator
       (we hit the cap; ship what we have rather than loop forever)
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from loguru import logger

from app.agents.nodes import (
    communicator_node,
    researcher_node,
    reviewer_node,
    strategist_node,
    writer_node,
)
from app.agents.state import AgentState, MAX_REVISIONS, initial_state


# ---------------------------------------------------------------------------
# Edge condition: route after reviewer
# ---------------------------------------------------------------------------
def _route_after_review(state: AgentState) -> str:
    verdict = state.get("review_verdict")
    revisions = state.get("revision_count", 0)

    if verdict == "approved":
        return "communicator"
    if verdict == "rejected":
        # Hard reject — don't loop, just ship with a warning. The frontend
        # will see review_verdict="rejected" and can flag it.
        logger.warning("Reviewer rejected; sending to communicator anyway")
        return "communicator"
    if verdict == "needs_revision" and revisions < MAX_REVISIONS:
        logger.info(f"Looping to writer (revision {revisions}/{MAX_REVISIONS})")
        return "writer"
    # Hit revision cap — finalize what we have.
    logger.info(f"Revision cap hit ({revisions}); sending to communicator")
    return "communicator"


# ---------------------------------------------------------------------------
# Graph construction (called once at module import)
# ---------------------------------------------------------------------------
def build_graph():
    """
    Build and compile the LangGraph StateGraph.

    Returns a compiled graph with .ainvoke(state) and .astream(state) methods.
    """
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("strategist", strategist_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("communicator", communicator_node)

    # Linear path through the planning + drafting phase
    graph.add_edge(START, "strategist")
    graph.add_edge("strategist", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "reviewer")

    # Conditional branch after review
    graph.add_conditional_edges(
        "reviewer",
        _route_after_review,
        {
            "writer": "writer",
            "communicator": "communicator",
        },
    )

    # Communicator is the terminal node
    graph.add_edge("communicator", END)

    return graph.compile()


# Module-level compiled graph. LangGraph compilation is fast but not free,
# so we do it once at import time.
_compiled_graph = build_graph()


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------
class AgentGraph:
    """
    Thin wrapper around the compiled graph with a friendly API.

    Services use:
        result = await agent_graph.run(
            company_id="acme",
            run_id="...",
            task="Write a LinkedIn post about our new feature X",
            content_type="linkedin_post",
        )
    """

    def __init__(self) -> None:
        self.graph = _compiled_graph

    async def run(
        self,
        *,
        company_id: str,
        run_id: str,
        task: str,
        content_type: str,
        target_audience: str | None = None,
    ) -> AgentState:
        """Invoke the graph end-to-end. Returns the final state."""
        state = initial_state(
            company_id=company_id,
            run_id=run_id,
            task=task,
            content_type=content_type,    # type: ignore[arg-type]
            target_audience=target_audience,
        )
        logger.info(
            f"Starting agent run {run_id} "
            f"(company={company_id}, type={content_type})"
        )
        # ainvoke returns the final accumulated state.
        final: AgentState = await self.graph.ainvoke(state)
        logger.info(
            f"Run {run_id} complete. "
            f"Trace: {final.get('node_trace')}, "
            f"verdict: {final.get('review_verdict')}, "
            f"revisions: {final.get('revision_count')}"
        )
        return final

    async def stream(
        self,
        *,
        company_id: str,
        run_id: str,
        task: str,
        content_type: str,
        target_audience: str | None = None,
    ):
        """
        Stream node-by-node updates. Useful for the Streamlit UI's progress bar
        and for /agent-run polling endpoints to surface live state.

        Yields dicts of the form {node_name: state_update}.
        """
        state = initial_state(
            company_id=company_id,
            run_id=run_id,
            task=task,
            content_type=content_type,    # type: ignore[arg-type]
            target_audience=target_audience,
        )
        async for update in self.graph.astream(state):
            yield update


# Module-level singleton.
agent_graph = AgentGraph()