"""
Streamlit entry point.

If the user isn't logged in: show the auth form.
If logged in: show a dashboard with quick stats + links to the other pages.

Streamlit auto-discovers files in pages/ and adds them to the sidebar nav
in alphabetical order. We prefix with numbers to control ordering.
"""
from __future__ import annotations

import streamlit as st

from components import (
    APIError,
    get_client,
    is_authenticated,
    render_auth_form,
    render_sidebar,
    show_api_error,
)

# Page config — must be first Streamlit call on every page
st.set_page_config(
    page_title="Company AI Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
)


def render_dashboard() -> None:
    """Logged-in landing page."""
    st.title("Welcome back")
    st.caption("Your company's AI workspace.")

    client = get_client()

    # Quick stats row
    col1, col2, col3 = st.columns(3)
    try:
        stats = client.stats()
        col1.metric("Documents", stats.get("document_count", 0))
        col2.metric("Chunks indexed", stats.get("chunk_count", 0))
        col3.metric("Vectors", stats.get("vector_count", 0))
    except APIError as e:
        show_api_error(e)

    st.markdown("---")

    # Quick navigation
    st.subheader("What would you like to do?")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.page_link(
            "pages/2_Documents.py",
            label="Upload documents",
            icon="📄",
            use_container_width=True,
        )
    with c2:
        st.page_link(
            "pages/3_Query.py",
            label="Ask the brain",
            icon="🔍",
            use_container_width=True,
        )
    with c3:
        st.page_link(
            "pages/4_Content_Studio.py",
            label="Generate content",
            icon="✨",
            use_container_width=True,
        )
    with c4:
        st.page_link(
            "pages/5_Email_Center.py",
            label="Email center",
            icon="📧",
            use_container_width=True,
        )
        
    with st.expander("🩺 System health", expanded=False):
        try:
            llm = client.health_llm()
            providers = llm.get("providers", {})
            for name, ok in providers.items():
                st.write(f"{'🟢' if ok else '🔴'} **{name}** — {'healthy' if ok else 'unreachable'}")
            breakers = llm.get("circuit_breakers", {})
            if any(b.get("open") for b in breakers.values()):
                st.warning("One or more circuit breakers are open — fallback in effect.")
        except APIError as e:
            show_api_error(e)


# Main entry
if is_authenticated():
    render_dashboard()
else:
    render_auth_form()

render_sidebar()