"""
Typed API client.

Why a class instead of raw `requests.post(...)` everywhere:
  - Single place to inject the auth token.
  - Single place to translate HTTP errors into a friendly Exception.
  - Easy to mock for testing.
  - Makes it obvious what endpoints exist (vs. searching the codebase).

Streamlit re-runs the script on every interaction, so we instantiate the
client once per request — cheap because httpx.Client uses connection pooling
internally only across calls within the same Client lifetime; for our
volume this is fine.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class APIError(Exception):
    """Raised when the backend returns a non-2xx response."""

    def __init__(self, message: str, status_code: int, code: str = "unknown") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class APIClient:
    """Thin synchronous wrapper around the FastAPI backend."""

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("BACKEND_URL", "http://localhost:8000")).rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _headers(self, extra: dict | None = None) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def _handle(self, r: httpx.Response) -> Any:
        """Raise APIError on non-2xx; return JSON otherwise."""
        if r.status_code == 204:
            return None
        if 200 <= r.status_code < 300:
            try:
                return r.json()
            except Exception:
                return r.text

        # Try to parse our standard error envelope first.
        try:
            payload = r.json()
            err = payload.get("error", {})
            raise APIError(
                message=err.get("message", r.text),
                status_code=r.status_code,
                code=err.get("code", "unknown"),
            )
        except APIError:
            raise
        except Exception:
            raise APIError(
                message=r.text or f"HTTP {r.status_code}",
                status_code=r.status_code,
            )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def signup(
        self, *, email: str, password: str, company_name: str, full_name: str | None = None
    ) -> dict:
        r = self._client.post(
            f"{self.base_url}/auth/signup",
            json={
                "email": email,
                "password": password,
                "company_name": company_name,
                "full_name": full_name,
            },
        )
        return self._handle(r)

    def login(self, *, email: str, password: str) -> dict:
        r = self._client.post(
            f"{self.base_url}/auth/login",
            json={"email": email, "password": password},
        )
        return self._handle(r)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def upload_document(self, *, filename: str, content: bytes, content_type: str) -> dict:
        # multipart upload — httpx wants files=
        files = {"file": (filename, content, content_type)}
        r = self._client.post(
            f"{self.base_url}/documents/upload",
            headers=self._headers(),
            files=files,
            timeout=120.0,   # ingest can take a moment
        )
        return self._handle(r)

    def list_documents(self) -> dict:
        r = self._client.get(f"{self.base_url}/documents", headers=self._headers())
        return self._handle(r)

    def delete_document(self, doc_id: str) -> None:
        r = self._client.delete(
            f"{self.base_url}/documents/{doc_id}", headers=self._headers()
        )
        self._handle(r)

    def stats(self) -> dict:
        r = self._client.get(f"{self.base_url}/documents/stats", headers=self._headers())
        return self._handle(r)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def query(self, *, question: str, top_k: int = 5, strategy: str = "mmr") -> dict:
        r = self._client.post(
            f"{self.base_url}/query",
            headers=self._headers(),
            json={"question": question, "top_k": top_k, "strategy": strategy},
            timeout=60.0,
        )
        return self._handle(r)

    # ------------------------------------------------------------------
    # Content generation
    # ------------------------------------------------------------------
    def generate_content(
        self,
        *,
        task: str,
        content_type: str,
        target_audience: str | None = None,
    ) -> dict:
        r = self._client.post(
            f"{self.base_url}/generate-content",
            headers=self._headers(),
            json={
                "task": task,
                "content_type": content_type,
                "target_audience": target_audience,
            },
            timeout=180.0,   # full agent pipeline can run long
        )
        return self._handle(r)

    def get_agent_run(self, run_id: str) -> dict:
        r = self._client.get(
            f"{self.base_url}/agent-run/{run_id}", headers=self._headers()
        )
        return self._handle(r)

    def list_agent_runs(self) -> dict:
        r = self._client.get(f"{self.base_url}/agent-run", headers=self._headers())
        return self._handle(r)

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    def draft_email(
        self,
        *,
        to_address: str,
        subject: str | None = None,
        body: str | None = None,
        generation_task: str | None = None,
    ) -> dict:
        r = self._client.post(
            f"{self.base_url}/send-email",
            headers=self._headers(),
            json={
                "to_address": to_address,
                "subject": subject,
                "body": body,
                "generation_task": generation_task,
            },
            timeout=180.0,
        )
        return self._handle(r)

    def approve_email(self, *, email_id: str, approve: bool = True) -> dict:
        r = self._client.post(
            f"{self.base_url}/approve-email",
            headers=self._headers(),
            json={"email_id": email_id, "approve": approve},
            timeout=30.0,
        )
        return self._handle(r)

    def list_emails(self) -> dict:
        r = self._client.get(f"{self.base_url}/emails", headers=self._headers())
        return self._handle(r)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> dict:
        r = self._client.get(f"{self.base_url}/health")
        return self._handle(r)

    def health_llm(self) -> dict:
        r = self._client.get(f"{self.base_url}/health/llm")
        return self._handle(r)