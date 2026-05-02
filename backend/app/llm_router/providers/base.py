"""
Abstract base class for LLM providers.

Every concrete provider (Groq, Ollama) implements this interface so the
router can swap them transparently. We intentionally keep the surface tiny:
- complete(messages, **kwargs) -> str
- stream(messages, **kwargs) -> AsyncIterator[str]
- health_check() -> bool

If we later want function calling / tool use, we'll add it here once and
let each provider implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal


# ---------------------------------------------------------------------------
# Message format (provider-agnostic)
# ---------------------------------------------------------------------------
Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class CompletionRequest:
    """
    What the router/agents pass to a provider.

    Keeping this as a dataclass (not raw kwargs) means we get a single place
    to add new params (response_format, tools, etc.) later without touching
    every provider.
    """
    messages: list[Message]
    model: str | None = None              # provider-specific override
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 1.0
    extra: dict = field(default_factory=dict)  # provider-specific escape hatch


@dataclass
class CompletionResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: dict | None = None  # original provider response, for debugging


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------
class LLMProvider(ABC):
    """All concrete providers inherit from this."""

    name: str = "base"          # short identifier, e.g. "groq", "ollama"
    default_model: str = ""     # set by subclass

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """One-shot completion. Raises ProviderError on failure."""
        ...

    @abstractmethod
    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[str]:
        """Stream tokens. Each yielded string is a delta, not the full text."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Quick liveness check used by the router for circuit-breaking."""
        ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class ProviderError(Exception):
    """Base class for all LLM provider failures."""

    def __init__(self, message: str, provider: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderRateLimitError(ProviderError):
    """429 from the provider. Always retryable (after backoff)."""

    def __init__(self, message: str, provider: str) -> None:
        super().__init__(message, provider, retryable=True)


class ProviderAuthError(ProviderError):
    """401/403. NOT retryable — config issue."""

    def __init__(self, message: str, provider: str) -> None:
        super().__init__(message, provider, retryable=False)


class ProviderUnavailableError(ProviderError):
    """5xx, network, timeout. Retryable."""

    def __init__(self, message: str, provider: str) -> None:
        super().__init__(message, provider, retryable=True)


class AllProvidersFailedError(Exception):
    """Raised by the router when every provider in the fallback chain fails."""

    def __init__(self, errors: dict[str, Exception]) -> None:
        self.errors = errors
        msg = "All providers failed: " + ", ".join(
            f"{p}={type(e).__name__}({e})" for p, e in errors.items()
        )
        super().__init__(msg)