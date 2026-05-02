"""
Auth helpers for the Streamlit app.

Two pieces:
  - render_auth_form(): the login + signup screen (used as the home page).
  - require_login(): drop into the top of every protected page; redirects
    to login if no token is in session_state.

Streamlit re-runs scripts top-to-bottom on every interaction. We persist
auth across runs in st.session_state, which is per-browser-session.
"""
from __future__ import annotations

import streamlit as st

from components.api_client import APIClient, APIError


def get_client() -> APIClient:
    """Build an API client with the current session token (if any)."""
    return APIClient(token=st.session_state.get("token"))


def is_authenticated() -> bool:
    return bool(st.session_state.get("token"))


def logout() -> None:
    for key in ("token", "user_id", "company_id", "email"):
        st.session_state.pop(key, None)
    st.rerun()


def require_login() -> None:
    """Call at the top of every protected page."""
    if not is_authenticated():
        st.warning("Please log in to continue.")
        st.page_link("streamlit_app.py", label="← Go to login", icon="🔑")
        st.stop()


# ---------------------------------------------------------------------------
# Login + signup form
# ---------------------------------------------------------------------------
def render_auth_form() -> None:
    """Render tabs for login + signup. Sets session_state on success."""
    st.title("🤖 Company AI Assistant")
    st.caption("Sign in to your company's AI workspace.")

    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email", autocomplete="email")
            password = st.text_input(
                "Password", type="password", key="login_password"
            )
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            _do_login(email, password)

    with tab_signup:
        with st.form("signup_form"):
            company_name = st.text_input(
                "Company name", placeholder="Acme Corp"
            )
            full_name = st.text_input("Your name (optional)")
            email = st.text_input(
                "Work email", key="signup_email", autocomplete="email"
            )
            password = st.text_input(
                "Password (min 8 chars)",
                type="password",
                key="signup_password",
            )
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            _do_signup(
                email=email,
                password=password,
                company_name=company_name,
                full_name=full_name or None,
            )


def _do_login(email: str, password: str) -> None:
    if not email or not password:
        st.error("Email and password are required.")
        return
    client = APIClient()  # no token yet
    try:
        with st.spinner("Logging in..."):
            result = client.login(email=email, password=password)
    except APIError as e:
        st.error(f"Login failed: {e.message}")
        return
    _persist_auth(result, email)
    st.success("Logged in. Redirecting...")
    st.rerun()


def _do_signup(
    *, email: str, password: str, company_name: str, full_name: str | None
) -> None:
    if not email or not password or not company_name:
        st.error("Email, password, and company name are required.")
        return
    if len(password) < 8:
        st.error("Password must be at least 8 characters.")
        return
    client = APIClient()
    try:
        with st.spinner("Creating account..."):
            result = client.signup(
                email=email,
                password=password,
                company_name=company_name,
                full_name=full_name,
            )
    except APIError as e:
        st.error(f"Signup failed: {e.message}")
        return
    _persist_auth(result, email)
    st.success("Account created. Welcome!")
    st.rerun()


def _persist_auth(login_response: dict, email: str) -> None:
    st.session_state["token"] = login_response["access_token"]
    st.session_state["user_id"] = login_response["user_id"]
    st.session_state["company_id"] = login_response["company_id"]
    st.session_state["email"] = email


# ---------------------------------------------------------------------------
# Sidebar — render on every page
# ---------------------------------------------------------------------------
def render_sidebar() -> None:
    """Show user info + logout button in the sidebar."""
    with st.sidebar:
        st.markdown("---")
        if is_authenticated():
            st.caption(f"Signed in as **{st.session_state.get('email', 'user')}**")
            st.caption(f"Company: `{st.session_state.get('company_id', '')[:8]}...`")
            if st.button("Log out", use_container_width=True):
                logout()