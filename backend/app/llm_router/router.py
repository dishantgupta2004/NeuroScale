"""
LLM Router — task-aware provider selection with retry + fallback + breaker.

How a request flows
-------------------
    agent calls router.complete(messages, task_type=TaskType.REASONING)
        │
        ▼
    Router picks a primary chain based on task_type:
        REASONING       -> [Groq(70b), Ollama]
        FAST_GENERATION -> [Groq(8b),  Ollama]
        SENSITIVE       -> [Ollama,    Groq(8b)]   <- internal data first
        LONG_CONTEXT    -> [Groq(70b), Ollama]
        │
        ▼
    For each provider in chain:
        - skip if circuit breaker is OPEN
        - call provider.complete with @with_retry decorator
        - on success: record_success, return
        - on failure: record_failure, log, try next provider
        │
        ▼
    If every provider fails -> raise AllProvidersFailedError
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from loguru import logger

from app.config import settings
from app.llm_router.providers import (
    AllProvidersFailedError,
    CompletionRequest,
    CompletionResponse,
    GroqProvider,
    LLMProvider,
    Message,
    OllamaProvider,
    ProviderAuthError,
    ProviderError,
)
from app.llm_router.retry import CircuitBreaker, with_retry


# ---------------------------------------------------------------------------
# Task taxonomy
# ---------------------------------------------------------------------------
class TaskType(str, Enum):
    """
    Used by agents to declare *what kind of work* they want done.
    The router maps this to a provider chain.
    """
    FAST_GENERATION = "fast_generation"   # writing, drafting, social posts
    REASONING = "reasoning"               # planning, strategy, review
    SENSITIVE = "sensitive"               # internal data — local-first
    LONG_CONTEXT = "long_context"         # big RAG dumps


# ---------------------------------------------------------------------------
# Provider chain config (declarative)
# ---------------------------------------------------------------------------
@dataclass
class _ChainStep:
    provider_name: str          # "groq" or "ollama"
    model: str | None = None    # None = use provider default


# Order matters: index 0 = primary, others = fallbacks in order.
_CHAINS: dict[TaskType, list[_ChainStep]] = {
    TaskType.FAST_GENERATION: [
        _ChainStep("groq", settings.groq_model_fast),
        _ChainStep("ollama", None),
    ],
    TaskType.REASONING: [
        _ChainStep("groq", settings.groq_model_reasoning),
        _ChainStep("ollama", None),
    ],
    TaskType.SENSITIVE: [
        # Local first for sensitive content. Groq is a cautious fallback —
        # only used if the local box is on fire.
        _ChainStep("ollama", None),
        _ChainStep("groq", settings.groq_model_fast),
    ],
    TaskType.LONG_CONTEXT: [
        _ChainStep("groq", settings.groq_model_reasoning),
        _ChainStep("ollama", None),
    ],
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class LLMRouter:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {
            "groq": GroqProvider(),
            "ollama": OllamaProvider(),
        }
        self._breaker = CircuitBreaker(
            failure_threshold=5,
            cooldown_seconds=60.0,
        )

    def get_provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        return self._providers[name]

    def chain_for(self, task: TaskType) -> list[_ChainStep]:
        return _CHAINS[task]

    # ------------------------------------------------------------------
    # Internal: single-provider call wrapped in retry
    # ------------------------------------------------------------------
    @with_retry(max_attempts=3, initial_wait=0.5, max_wait=8.0)
    async def _call_with_retry(
        self,
        provider: LLMProvider,
        request: CompletionRequest,
    ) -> CompletionResponse:
        return await provider.complete(request)

    # ------------------------------------------------------------------
    # Public: task-routed completion
    # ------------------------------------------------------------------
    async def complete(
        self,
        *,
        messages: list[Message],
        task_type: TaskType = TaskType.FAST_GENERATION,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        top_p: float = 1.0,
        force_provider: str | None = None,
    ) -> CompletionResponse:
        """
        Run a chat completion through the routed provider chain.

        Parameters
        ----------
        messages : conversation in chronological order.
        task_type : determines the fallback chain.
        force_provider : skip routing, use this provider directly. Useful for
                         tests and debugging. Still gets retry but NOT
                         fallback (since the caller explicitly chose).
        """
        # Build the chain.
        if force_provider:
            chain = [_ChainStep(force_provider, None)]
        else:
            chain = _CHAINS[task_type]

        errors: dict[str, Exception] = {}

        for step in chain:
            pname = step.provider_name

            # Circuit breaker check
            if self._breaker.is_open(pname):
                logger.info(f"Skipping {pname} — circuit breaker open")
                errors[pname] = RuntimeError("circuit_open")
                continue

            provider = self._providers[pname]
            req = CompletionRequest(
                messages=messages,
                model=step.model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )

            try:
                logger.debug(
                    f"Routing task={task_type.value} -> {pname} "
                    f"(model={step.model or provider.default_model})"
                )
                resp = await self._call_with_retry(provider, req)
                self._breaker.record_success(pname)
                return resp

            except ProviderAuthError as e:
                # Don't retry, don't trip the breaker too hard, but DO move on
                # to fallback. An auth error means this provider is misconfigured;
                # better to serve the request via fallback than to fail.
                logger.error(f"{pname} auth error: {e}")
                errors[pname] = e
                self._breaker.record_failure(pname)
                continue

            except ProviderError as e:
                logger.warning(f"{pname} failed after retries: {e}")
                errors[pname] = e
                self._breaker.record_failure(pname)
                continue

            except Exception as e:  # pragma: no cover — unexpected
                logger.exception(f"{pname} unexpected error: {e}")
                errors[pname] = e
                self._breaker.record_failure(pname)
                continue

        raise AllProvidersFailedError(errors)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    async def health(self) -> dict:
        """Used by /health endpoint and dashboards."""
        results = {}
        for name, prov in self._providers.items():
            try:
                results[name] = await prov.health_check()
            except Exception as e:
                results[name] = False
                logger.warning(f"{name} health raise: {e}")
        return {
            "providers": results,
            "circuit_breakers": self._breaker.status(),
        }


# Module-level singleton.
router = LLMRouter()