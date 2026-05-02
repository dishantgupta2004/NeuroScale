"""
📧 Email Center.

Two-step flow with explicit human approval:
  1. Draft (manually or via agent)  -> backend creates EmailLog (pending_approval)
  2. Approve / Reject               -> backend either calls SES (sent) or marks rejected

The backend enforces the approval gate; the UI just makes it obvious.
"""
from __future__ import annotations

import streamlit as st

from components import (
    APIError,
    empty_state,
    get_client,
    render_sidebar,
    require_login,
    show_api_error,
    status_badge,
)

st.set_page_config(page_title="Email Center", page_icon="📧", layout="wide")
require_login()
render_sidebar()

st.title("📧 Email Center")
st.caption(
    "Draft emails (manually or with the AI), review them, then approve to send. "
    "Nothing leaves your account until you click approve."
)

client = get_client()


# ---------------------------------------------------------------------------
# Render helper (defined first so it's available below)
# ---------------------------------------------------------------------------
def render_email_card(email: dict, *, with_actions: bool) -> None:
    """Render one email row with optional approve/reject buttons."""
    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].markdown(f"**To:** {email['to_address']}")
        top[1].markdown(status_badge(email["status"]))
        st.markdown(f"**Subject:** {email['subject']}")
        st.caption(f"Created {email['created_at'][:19].replace('T', ' ')}")

        with st.expander("Body", expanded=False):
            st.markdown(
                f"<div style='white-space: pre-wrap; font-family: ui-monospace, monospace; "
                f"font-size: 0.85rem;'>{email['body']}</div>",
                unsafe_allow_html=True,
            )

        if email.get("error"):
            st.error(f"Error: {email['error']}")
        if email.get("ses_message_id"):
            st.caption(f"SES Message ID: `{email['ses_message_id']}`")

        if with_actions:
            actions = st.columns(2)
            if actions[0].button(
                "✅ Approve & send",
                key=f"approve-{email['id']}",
                type="primary",
                use_container_width=True,
            ):
                try:
                    with st.spinner("Sending via SES..."):
                        client.approve_email(email_id=email["id"], approve=True)
                    st.toast("Email sent", icon="✅")
                    st.rerun()
                except APIError as e:
                    show_api_error(e)
            if actions[1].button(
                "❌ Reject",
                key=f"reject-{email['id']}",
                use_container_width=True,
            ):
                try:
                    client.approve_email(email_id=email["id"], approve=False)
                    st.toast("Email rejected", icon="❌")
                    st.rerun()
                except APIError as e:
                    show_api_error(e)


# ---------------------------------------------------------------------------
# Two columns: composer on the left, queue on the right
# ---------------------------------------------------------------------------
left, right = st.columns([3, 2])

# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------
with left:
    st.subheader("Compose")

    mode = st.radio(
        "Mode",
        options=["AI-drafted", "Write it myself"],
        horizontal=True,
        label_visibility="collapsed",
    )

    with st.form("draft_form", clear_on_submit=False):
        to_address = st.text_input(
            "To",
            placeholder="recipient@example.com",
            help=(
                "If you're in the SES sandbox, this address must be verified "
                "in your AWS SES console first."
            ),
        )

        subject = None
        body = None
        generation_task = None

        if mode == "AI-drafted":
            generation_task = st.text_area(
                "Tell the AI what to write",
                placeholder=(
                    "e.g. Friendly intro email about our async export feature. "
                    "Mention the 50% time savings stat from our benchmark."
                ),
                height=140,
            )
            subject = st.text_input(
                "Subject (optional — AI will generate one if blank)"
            )
        else:
            subject = st.text_input("Subject")
            body = st.text_area("Body", height=200)

        submitted = st.form_submit_button("📝 Create draft", type="primary")

    if submitted:
        if not to_address:
            st.error("Recipient address is required.")
        elif mode == "AI-drafted" and not (generation_task or "").strip():
            st.error("Tell the AI what to write.")
        elif mode == "Write it myself" and (not body or not subject):
            st.error("Subject and body are required for manual mode.")
        else:
            try:
                with st.spinner(
                    "Drafting..." if mode == "Write it myself"
                    else "Running agents to draft email (~30s)..."
                ):
                    client.draft_email(
                        to_address=to_address.strip(),
                        subject=(subject or "").strip() or None,
                        body=body.strip() if body else None,
                        generation_task=(
                            generation_task.strip() if generation_task else None
                        ),
                    )
                st.toast("Draft created — review on the right →", icon="📝")
                st.rerun()
            except APIError as e:
                show_api_error(e)


# ---------------------------------------------------------------------------
# Queue + approval
# ---------------------------------------------------------------------------
with right:
    st.subheader("Drafts & sent")

    try:
        payload = client.list_emails()
        emails = payload.get("emails", [])
    except APIError as e:
        show_api_error(e)
        emails = []

    if not emails:
        empty_state(
            icon="📭",
            title="No emails yet",
            description="Drafts you create will appear here.",
        )
    else:
        # Show pending approval first, then the rest
        pending = [e for e in emails if e["status"] == "pending_approval"]
        others = [e for e in emails if e["status"] != "pending_approval"]

        if pending:
            st.markdown("##### ⏳ Awaiting approval")
            for e in pending:
                render_email_card(e, with_actions=True)

        if others:
            st.markdown("##### 📜 History")
            for e in others[:20]:
                render_email_card(e, with_actions=False)