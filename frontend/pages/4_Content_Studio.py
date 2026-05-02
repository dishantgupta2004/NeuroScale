"""
✨ Content Studio.

This is where the full multi-agent pipeline gets exercised. The user picks
a content type, describes what they want, and the backend runs:

    Strategist → Researcher → Writer → Reviewer → Communicator

We render the result with:
  - Final content (front and center)
  - Review verdict + revision count (so the user knows it was vetted)
  - Citations from the research step
  - Node trace (collapsed — for the curious)
  - Plan + key points (collapsed)
  - One-click "Create email from this" for the email use case

History of recent runs lives in the right column.
"""
from __future__ import annotations

import streamlit as st

from components import (
    APIError,
    empty_state,
    get_client,
    render_citations,
    render_sidebar,
    require_login,
    show_api_error,
    status_badge,
)

st.set_page_config(page_title="Content Studio", page_icon="✨", layout="wide")
require_login()
render_sidebar()

st.title("✨ Content Studio")
st.caption(
    "Brief the AI on what you want; the agent crew plans, researches, "
    "drafts, reviews, and polishes."
)

client = get_client()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "current_run" not in st.session_state:
    st.session_state.current_run = None     # latest AgentRunResponse dict


# ---------------------------------------------------------------------------
# Layout: form on the left, history on the right
# ---------------------------------------------------------------------------
left, right = st.columns([2, 1])

# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------
with left:
    st.subheader("Brief")
    with st.form("generate_form"):
        content_type = st.selectbox(
            "Content type",
            options=[
                ("linkedin_post", "💼 LinkedIn post"),
                ("blog", "📝 Blog post"),
                ("twitter_post", "🐦 Twitter post"),
                ("email", "📧 Email"),
                ("research_summary", "🔬 Research summary"),
            ],
            format_func=lambda x: x[1],
        )
        task = st.text_area(
            "What should the AI write?",
            placeholder=(
                "e.g. Announce our new async export feature, focusing on "
                "developer time savings. Keep it punchy and link to the docs."
            ),
            height=120,
        )
        target_audience = st.text_input(
            "Target audience (optional)",
            placeholder="e.g. senior backend engineers at SaaS companies",
        )
        submitted = st.form_submit_button("✨ Generate", type="primary")

    if submitted:
        if not task.strip() or len(task.strip()) < 5:
            st.error("Please describe what you want in more detail.")
        else:
            try:
                with st.spinner(
                    "Running the agent crew (this can take 20–60 seconds)..."
                ):
                    result = client.generate_content(
                        task=task.strip(),
                        content_type=content_type[0],
                        target_audience=target_audience.strip() or None,
                    )
                st.session_state.current_run = result
                if result.get("status") == "complete":
                    st.toast("✅ Content ready", icon="✨")
                else:
                    st.toast("⚠️ Run finished with issues", icon="⚠️")
            except APIError as e:
                show_api_error(e)

    # ---------- Render current run ----------
    run = st.session_state.current_run
    if run:
        st.markdown("---")
        st.subheader("Result")

        meta_cols = st.columns(3)
        meta_cols[0].markdown(f"**Status**\n\n{status_badge(run.get('status'))}")
        meta_cols[1].markdown(
            f"**Review**\n\n{status_badge(run.get('review_verdict'))}"
        )
        snapshot = run.get("state_snapshot") or {}
        revisions = snapshot.get("revision_count", 0)
        meta_cols[2].markdown(f"**Revisions**\n\n{revisions}")

        if run.get("error"):
            st.error(f"Error: {run['error']}")

        final_content = run.get("final_content")
        if final_content:
            st.markdown("#### Final content")
            st.markdown(
                f"<div style='background:#f6f8fa; border-radius:8px; padding:1rem 1.25rem; "
                f"border-left:4px solid #6366f1;'>{final_content}</div>",
                unsafe_allow_html=True,
            )
            st.text_area(
                "Copy-friendly version",
                value=final_content,
                height=200,
                label_visibility="collapsed",
            )

            # Quick action: turn this into an email draft
            if run.get("content_type") == "email":
                st.info(
                    "💡 Switch to **Email Center** to address this and send it."
                )
        else:
            st.warning("No final content was produced. Check the trace below.")

        # Citations
        citations = snapshot.get("citations", [])
        render_citations(citations)

        # Plan + key points
        plan = snapshot.get("plan")
        key_points = snapshot.get("key_points", [])
        if plan or key_points:
            with st.expander("🧭 Plan & key points", expanded=False):
                if plan:
                    st.markdown(f"**Plan:** {plan}")
                if key_points:
                    st.markdown("**Key points:**")
                    for kp in key_points:
                        st.markdown(f"- {kp}")
                tone = snapshot.get("tone_guide")
                if tone:
                    st.markdown(f"**Tone:** _{tone}_")

        # Reviewer feedback (if any)
        feedback = snapshot.get("review_feedback")
        if feedback:
            with st.expander("👀 Reviewer feedback", expanded=False):
                st.write(feedback)

        # Node trace
        trace = snapshot.get("node_trace", [])
        if trace:
            with st.expander("🔍 Agent trace", expanded=False):
                st.code(" → ".join(trace), language=None)


# ---------------------------------------------------------------------------
# History column
# ---------------------------------------------------------------------------
with right:
    st.subheader("Recent runs")
    try:
        history = client.list_agent_runs()
    except APIError as e:
        show_api_error(e)
        history = {"runs": []}

    runs = history.get("runs", [])
    if not runs:
        empty_state(
            icon="🎬",
            title="No runs yet",
            description="Your generated content will appear here.",
        )
    else:
        for r in runs[:15]:
            label = (
                f"{status_badge(r['status'])}  ·  {r['content_type']}\n\n"
                f"_{r['task'][:80]}{'...' if len(r['task']) > 80 else ''}_"
            )
            with st.container(border=True):
                st.markdown(label)
                if st.button(
                    "View", key=f"view-{r['id']}", use_container_width=True
                ):
                    try:
                        st.session_state.current_run = client.get_agent_run(r["id"])
                        st.rerun()
                    except APIError as e:
                        show_api_error(e)