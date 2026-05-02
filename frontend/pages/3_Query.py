"""
🔍 Query page.

Chat-style RAG interface. Each message + answer + citations is kept in
session_state so the user can scroll back through their conversation.
This is the simple "ask the brain" path — no agent pipeline, just
retrieve + answer.
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
)

st.set_page_config(page_title="Query", page_icon="🔍", layout="wide")
require_login()
render_sidebar()

st.title("🔍 Ask the brain")
st.caption(
    "Quick Q&A grounded in your uploaded documents. "
    "For longer-form content (blogs, posts, emails), use Content Studio instead."
)

client = get_client()

# ---------------------------------------------------------------------------
# Session state — chat history
# ---------------------------------------------------------------------------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # list of {"role", "content", "citations"?}


# ---------------------------------------------------------------------------
# Sidebar controls (within the page sidebar, separate from app sidebar)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Retrieval settings")
    top_k = st.slider("Sources to retrieve", min_value=1, max_value=15, value=5)
    strategy = st.radio(
        "Strategy",
        options=["mmr", "similarity"],
        index=0,
        help="MMR diversifies; similarity returns most-similar chunks.",
    )
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()


# ---------------------------------------------------------------------------
# Render history
# ---------------------------------------------------------------------------
if not st.session_state.chat_history:
    empty_state(
        icon="💭",
        title="Ask anything about your company",
        description="e.g. 'What is our mission?' or 'Summarize our pricing strategy'",
    )

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("citations"):
            render_citations(msg["citations"])


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
question = st.chat_input("Ask a question...")

if question:
    # 1. Show user message immediately
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 2. Call backend
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = client.query(
                    question=question, top_k=top_k, strategy=strategy
                )
                answer = result.get("answer", "")
                citations = result.get("citations", [])
                st.markdown(answer)
                render_citations(citations)
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": answer, "citations": citations}
                )
            except APIError as e:
                show_api_error(e)
                # Don't append failed responses — let user retry.