"""
Retry + circuit breaker for LLM calls.

Two layers of resilience:

1. Retry (per-call): tenacity-driven exponential backoff for transient errors.
   We only retry errors marked .retryable=True (rate limits, 5xx, timeouts).
   Auth errors fail fast — no point retrying a bad API key.

2. Circuit breaker (per-provider): if a provider fails repeatedly within a
   short window, we mark it "open" and skip it entirely for a cooldown
   period. This prevents the router from wasting time + budget hammering
   a provider that is clearly down.

Why both?
- Retry handles "blip" failures (one timeout, one 502).
- Circuit breaker handles "the provider is down for 10 minutes" — instead
  of 3-retrying every request and slowing every user request to a crawl,
  we just skip to fallback immediately.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Awaitable, Callable, TypeVar

from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

from app.llm_router.providers.base import ProviderError

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------
def _is_retryable(e: BaseException) -> bool:
    return isinstance(e, ProviderError) and e.retryable


def with_retry(
    max_attempts: int = 3,
    initial_wait: float = 0.5,
    max_wait: float = 8.0,
) -> Callable:
    """
    Decorator: retry an async function with exponential backoff on retryable
    ProviderError. Re-raises the last exception when attempts are exhausted.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(
                        multiplier=initial_wait, max=max_wait
                    ),
                    retry=retry_if_exception(_is_retryable),
                    reraise=True,
                ):
                    with attempt:
                        return await fn(*args, **kwargs)
            except RetryError as re:
                # Should not happen with reraise=True, but be defensive.
                raise re.last_attempt.exception()  # type: ignore[misc]
            # Unreachable, but keeps type checker happy.
            raise RuntimeError("retry loop exited without returning")

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
@dataclass
class _BreakerState:
    failure_count: int = 0
    opened_at: float | None = None  # epoch when circuit opened


class CircuitBreaker:
    """
    Simple per-key circuit breaker.

    States:
        - CLOSED (default): calls pass through. Failures increment counter.
        - OPEN: failure_count >= threshold. Calls are short-circuited
          (is_open() returns True) until cooldown elapses.
        - After cooldown: a single "probe" call is allowed; on success the
          breaker closes again, on failure it re-opens.

    We don't track a separate HALF_OPEN state — `is_open()` returning False
    after cooldown is effectively the probe.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state: dict[str, _BreakerState] = {}

    def _get(self, key: str) -> _BreakerState:
        if key not in self._state:
            self._state[key] = _BreakerState()
        return self._state[key]

    def is_open(self, key: str) -> bool:
        s = self._get(key)
        if s.opened_at is None:
            return False
        if time.monotonic() - s.opened_at >= self.cooldown_seconds:
            # Cooldown elapsed — let one probe through.
            logger.info(f"Circuit breaker [{key}] cooldown elapsed, probing")
            s.opened_at = None
            s.failure_count = 0
            return False
        return True

    def record_success(self, key: str) -> None:
        s = self._get(key)
        if s.failure_count or s.opened_at:
            logger.info(f"Circuit breaker [{key}] reset after success")
        s.failure_count = 0
        s.opened_at = None

    def record_failure(self, key: str) -> None:
        s = self._get(key)
        s.failure_count += 1
        if s.failure_count >= self.failure_threshold and s.opened_at is None:
            s.opened_at = time.monotonic()
            logger.warning(
                f"Circuit breaker [{key}] OPENED after "
                f"{s.failure_count} failures (cooldown {self.cooldown_seconds}s)"
            )

    def status(self) -> dict[str, dict]:
        """For /health and dashboards."""
        now = time.monotonic()
        return {
            k: {
                "open": s.opened_at is not None
                and (now - s.opened_at) < self.cooldown_seconds,
                "failure_count": s.failure_count,
                "opened_seconds_ago": (now - s.opened_at) if s.opened_at else None,
            }
            for k, s in self._state.items()
        }