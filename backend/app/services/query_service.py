"""
Query service.

Lightweight RAG Q&A — no multi-agent overhead. Use this when the user just
wants to ask a question of their company brain, not generate a polished
artifact.

Flow:
  1. Retrieve top-k chunks (MMR by default).
  2. Build a compact prompt with the chunks as context.
  3. Call Groq fast model with TaskType.FAST_GENERATION.
  4. Return answer + citations.
"""
from __future__ import annotations

from app.llm_router import Message, TaskType, router
from app.models.content import QueryRequest, QueryResponse
from app.rag import retriever


_SYSTEM_PROMPT = (
    "You answer questions strictly using the provided company knowledge. "
    "If the answer isn't in the context, say so plainly. "
    "Cite chunks inline using the [n] markers from the context."
)

_USER_TEMPLATE = """Question: {question}

Company knowledge:
{context}

Answer the question using only the company knowledge above. Cite sources as [1], [2], etc."""


class QueryService:
    async def answer(
        self, *, company_id: str, payload: QueryRequest
    ) -> QueryResponse:
        ctx = await retriever.retrieve(
            company_id=company_id,
            query=payload.question,
            top_k=payload.top_k,
            strategy=payload.strategy,
        )

        if not ctx.raw_results:
            return QueryResponse(
                answer="I don't have any company knowledge yet. Upload documents first.",
                citations=[],
            )

        prompt = _USER_TEMPLATE.format(
            question=payload.question, context=ctx.formatted_text
        )
        resp = await router.complete(
            messages=[
                Message("system", _SYSTEM_PROMPT),
                Message("user", prompt),
            ],
            task_type=TaskType.FAST_GENERATION,
            temperature=0.2,
            max_tokens=800,
        )
        return QueryResponse(answer=resp.text.strip(), citations=ctx.citations)


query_service = QueryService()