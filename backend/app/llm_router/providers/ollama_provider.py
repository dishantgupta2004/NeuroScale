"""
Ollama provider.

We talk to Ollama's HTTP API directly via httpx instead of using the
ollama-python SDK. Reasons:
  - Fewer deps; httpx is already in the stack.
  - We get full control over timeouts and error handling.
  - Ollama's API is simple and stable (/api/chat).

Endpoint contract: https://github.com/ollama/ollama/blob/main/docs/api.md
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
from loguru import logger

from app.config import settings
from app.llm_router.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
)


class OllamaProvider(LLMProvider):
    name = "ollama"
    default_model = settings.ollama_model  # "llama3.1:8b"

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        # Ollama on CPU can be slow for the first token, so timeout is generous.
        # We use a long-lived AsyncClient for connection pooling.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_model(self, request: CompletionRequest) -> str:
        return request.model or self.default_model

    def _build_payload(self, request: CompletionRequest, stream: bool) -> dict:
        return {
            "model": self._resolve_model(request),
            "messages": [m.to_dict() for m in request.messages],
            "stream": stream,
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "num_predict": request.max_tokens,
            },
        }

    @staticmethod
    def _wrap_error(e: Exception) -> ProviderError:
        if isinstance(e, httpx.ConnectError):
            return ProviderUnavailableError(
                f"Cannot reach Ollama at {settings.ollama_base_url}: {e}",
                provider="ollama",
            )
        if isinstance(e, httpx.TimeoutException):
            return ProviderUnavailableError(
                f"Ollama timeout: {e}", provider="ollama"
            )
        if isinstance(e, httpx.HTTPStatusError):
            return ProviderUnavailableError(
                f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}",
                provider="ollama",
            )
        return ProviderUnavailableError(f"Unexpected: {e}", provider="ollama")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = self._resolve_model(request)
        payload = self._build_payload(request, stream=False)
        try:
            r = await self._client.post("/api/chat", json=payload)
            r.raise_for_status()
        except Exception as e:
            raise self._wrap_error(e) from e

        data = r.json()
        # Ollama's /api/chat returns: {"message": {"role": "...", "content": "..."}, ...}
        text = data.get("message", {}).get("content", "")
        return CompletionResponse(
            text=text,
            model=model,
            provider=self.name,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            raw=data,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        model = self._resolve_model(request)
        payload = self._build_payload(request, stream=True)

        async def _gen() -> AsyncIterator[str]:
            try:
                async with self._client.stream(
                    "POST", "/api/chat", json=payload
                ) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = obj.get("message", {}).get("content")
                        if delta:
                            yield delta
                        if obj.get("done"):
                            break
            except Exception as e:
                raise self._wrap_error(e) from e

        # We can't await an async generator factory in a method that returns one,
        # so we just return the generator directly. (model is captured for clarity.)
        _ = model
        return _gen()

    async def health_check(self) -> bool:
        """Hit /api/tags — fastest endpoint, just lists local models."""
        try:
            r = await self._client.get("/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False