"""
Tiny shared UI helpers. Keep this file small — anything bigger should
live as a proper component.
"""
from __future__ import annotations

import streamlit as st


# ---------------------------------------------------------------------------
# Status pills
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "ready": "🟢",
    "running": "🟡",
    "ingesting": "🟡",
    "complete": "🟢",
    "failed": "🔴",
    "send_failed": "🔴",
    "pending_approval": "🟠",
    "approved": "🔵",
    "sent": "🟢",
    "rejected": "⚫",
    "approved_review": "🟢",
    "needs_revision": "🟠",
}


def status_badge(status: str | None) -> str:
    if not status:
        return "—"
    icon = _STATUS_COLORS.get(status, "⚪")
    return f"{icon} {status.replace('_', ' ')}"


# ---------------------------------------------------------------------------
# Citation rendering
# ---------------------------------------------------------------------------
def render_citations(citations: list[dict]) -> None:
    """Render a citation list as a compact expander."""
    if not citations:
        return
    with st.expander(f"📚 Sources ({len(citations)})", expanded=False):
        for c in citations:
            idx = c.get("index", "?")
            src = c.get("source", "unknown")
            page = c.get("page", "?")
            score = c.get("score", 0.0)
            st.caption(f"**[{idx}]** {src} — page {page}  ·  score {score:.3f}")


# ---------------------------------------------------------------------------
# Error display
# ---------------------------------------------------------------------------
def show_api_error(e) -> None:
    """Pretty-print an APIError without leaking internals."""
    from components.api_client import APIError
    if isinstance(e, APIError):
        if e.status_code == 401:
            st.error("Your session expired. Please log in again.")
        elif e.status_code == 502:
            st.error(f"Upstream service issue: {e.message}")
        else:
            st.error(f"{e.message}")
    else:
        st.error(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------
def empty_state(icon: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <div style="text-align: center; padding: 3rem 1rem; opacity: 0.7;">
            <div style="font-size: 3rem;">{icon}</div>
            <div style="font-size: 1.25rem; font-weight: 600; margin-top: 0.5rem;">{title}</div>
            <div style="font-size: 0.95rem; margin-top: 0.25rem;">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )