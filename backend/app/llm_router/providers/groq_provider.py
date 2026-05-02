"""
Groq provider.

Uses the official `groq` SDK (installed transitively via langchain-groq, but
we use the SDK directly for tighter control over errors / streaming).

Model selection
---------------
default_model = llama-3.1-8b-instant (fast generation)
For reasoning tasks the router passes model=settings.groq_model_reasoning
(llama-3.3-70b-versatile) explicitly via CompletionRequest.model.
"""
from __future__ import annotations

from typing import AsyncIterator

from groq import AsyncGroq, APIError, APIStatusError, RateLimitError, APITimeoutError
from loguru import logger

from app.config import settings
from app.llm_router.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)


class GroqProvider(LLMProvider):
    name = "groq"
    default_model = settings.groq_model_fast  # "llama-3.1-8b-instant"

    def __init__(self) -> None:
        if not settings.groq_api_key:
            logger.warning(
                "GROQ_API_KEY is empty — GroqProvider will fail on first call. "
                "Set it in your .env."
            )
        # AsyncGroq is the official async client.
        # Timeout is intentionally short — Groq is meant to be sub-second.
        self.client = AsyncGroq(
            api_key=settings.groq_api_key or "missing",
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _map_error(e: Exception) -> ProviderError:
        """Translate Groq SDK exceptions into our provider error hierarchy."""
        if isinstance(e, RateLimitError):
            return ProviderRateLimitError(str(e), provider="groq")
        if isinstance(e, APIStatusError):
            status = getattr(e, "status_code", None)
            if status in (401, 403):
                return ProviderAuthError(str(e), provider="groq")
            if status and status >= 500:
                return ProviderUnavailableError(str(e), provider="groq")
        if isinstance(e, APITimeoutError):
            return ProviderUnavailableError(f"Timeout: {e}", provider="groq")
        if isinstance(e, APIError):
            return ProviderUnavailableError(str(e), provider="groq")
        # Unknown — treat as retryable.
        return ProviderUnavailableError(f"Unexpected: {e}", provider="groq")

    def _resolve_model(self, request: CompletionRequest) -> str:
        return request.model or self.default_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = self._resolve_model(request)
        try:
            resp = await self.client.chat.completions.create(
                model=model,
                messages=[m.to_dict() for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                top_p=request.top_p,
                stream=False,
            )
        except Exception as e:
            raise self._map_error(e) from e

        choice = resp.choices[0]
        usage = resp.usage
        return CompletionResponse(
            text=choice.message.content or "",
            model=model,
            provider=self.name,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        model = self._resolve_model(request)
        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=[m.to_dict() for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                top_p=request.top_p,
                stream=True,
            )
        except Exception as e:
            raise self._map_error(e) from e

        async def _gen() -> AsyncIterator[str]:
            try:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
            except Exception as e:
                raise self._map_error(e) from e

        return _gen()

    async def health_check(self) -> bool:
        """Tiny request to confirm the API + key work."""
        try:
            await self.client.chat.completions.create(
                model=self.default_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0.0,
            )
            return True
        except Exception as e:
            logger.warning(f"Groq health check failed: {e}")
            return False