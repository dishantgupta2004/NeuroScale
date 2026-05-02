"""
📄 Documents page.

Upload PDF/DOCX/TXT/MD into the company brain, list existing docs,
delete one if needed.
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

st.set_page_config(page_title="Documents", page_icon="📄", layout="wide")
require_login()
render_sidebar()

st.title("📄 Documents")
st.caption(
    "Feed your company's knowledge into the AI: vision docs, blogs, "
    "research, internal wikis. Each upload is chunked, embedded, and "
    "added to your private FAISS index."
)

client = get_client()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
st.subheader("Upload new document")

uploaded = st.file_uploader(
    "Drop a file here",
    type=["pdf", "docx", "txt", "md"],
    accept_multiple_files=False,
    label_visibility="collapsed",
)

if uploaded is not None:
    if st.button("Upload & ingest", type="primary"):
        try:
            with st.spinner(f"Ingesting {uploaded.name}..."):
                result = client.upload_document(
                    filename=uploaded.name,
                    content=uploaded.getvalue(),
                    content_type=uploaded.type or "application/octet-stream",
                )
            if result.get("status") == "ready":
                st.success(
                    f"✅ Uploaded — {result.get('chunk_count', 0)} chunks added to the brain."
                )
            else:
                st.warning(
                    f"⚠️ Upload status: {result.get('status')}. "
                    f"Error: {result.get('error') or 'unknown'}"
                )
            # Force a rerun so the doc list below picks up the new entry.
            st.rerun()
        except APIError as e:
            show_api_error(e)

st.markdown("---")


# ---------------------------------------------------------------------------
# List existing
# ---------------------------------------------------------------------------
st.subheader("Your documents")

try:
    payload = client.list_documents()
    docs = payload.get("documents", [])
except APIError as e:
    show_api_error(e)
    docs = []

if not docs:
    empty_state(
        icon="📭",
        title="No documents yet",
        description="Upload your first doc above to start building the brain.",
    )
else:
    # Header row
    cols = st.columns([3, 1, 1, 1.5, 1])
    cols[0].markdown("**Filename**")
    cols[1].markdown("**Status**")
    cols[2].markdown("**Chunks**")
    cols[3].markdown("**Uploaded**")
    cols[4].markdown("**Actions**")

    for doc in docs:
        cols = st.columns([3, 1, 1, 1.5, 1])
        cols[0].write(doc["filename"])
        cols[1].write(status_badge(doc["status"]))
        cols[2].write(doc["chunk_count"])
        cols[3].caption(doc["created_at"][:19].replace("T", " "))
        if cols[4].button("🗑️", key=f"del-{doc['id']}", help="Delete"):
            try:
                client.delete_document(doc["id"])
                st.toast(f"Deleted {doc['filename']}")
                st.rerun()
            except APIError as e:
                show_api_error(e)

        if doc.get("error"):
            st.error(f"  {doc['filename']}: {doc['error']}")