"""
LLM Router package — public API.

Usage from agents / services:

    from app.llm_router import router, TaskType, Message

    response = await router.complete(
        messages=[
            Message("system", "You are a helpful assistant."),
            Message("user", "Summarize this in 2 sentences: ..."),
        ],
        task_type=TaskType.FAST_GENERATION,
        temperature=0.4,
    )
    print(response.text)
"""
from app.llm_router.providers import (
    AllProvidersFailedError,
    CompletionRequest,
    CompletionResponse,
    Message,
    ProviderError,
)
from app.llm_router.router import LLMRouter, TaskType, router

__all__ = [
    "AllProvidersFailedError",
    "CompletionRequest",
    "CompletionResponse",
    "LLMRouter",
    "Message",
    "ProviderError",
    "TaskType",
    "router",
]