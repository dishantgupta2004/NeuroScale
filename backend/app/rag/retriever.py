"""
Retriever — the only RAG interface that agents and routes should touch.

Agents shouldn't know about FAISS, embeddings, or chunks. They ask:
"give me context for this query in this company" — the retriever returns
formatted, ready-to-prompt text + structured citations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.rag.vectorstore import vectorstore, SearchResult


@dataclass
class RetrievedContext:
    """What the retriever returns to callers."""
    formatted_text: str               # ready to drop into an LLM prompt
    citations: list[dict]             # [{source, page, doc_id, score}, ...]
    raw_results: list[SearchResult]   # for callers that want the chunks


class Retriever:
    """Thin orchestration layer over the vectorstore."""

    async def retrieve(
        self,
        *,
        company_id: str,
        query: str,
        top_k: int = 5,
        strategy: Literal["similarity", "mmr"] = "mmr",
    ) -> RetrievedContext:
        """
        Retrieve context for a query.

        strategy:
          - "similarity" → fastest, may return near-duplicates.
          - "mmr" → diversified, better for broad questions.
        """
        if strategy == "mmr":
            results = await vectorstore.search_mmr(
                company_id=company_id, query=query, top_k=top_k
            )
        else:
            results = await vectorstore.search(
                company_id=company_id, query=query, top_k=top_k
            )

        return RetrievedContext(
            formatted_text=self._format_for_prompt(results),
            citations=self._build_citations(results),
            raw_results=results,
        )

    @staticmethod
    def _format_for_prompt(results: list[SearchResult]) -> str:
        """
        Format chunks into a numbered context block the LLM can cite from.

        Example output:
            [1] (vision.pdf, p.2): We aim to make small businesses ...
            [2] (about.docx, p.1): Founded in 2021 by ...
        """
        if not results:
            return "(no relevant context found)"
        lines = []
        for i, r in enumerate(results, start=1):
            src = r.chunk.metadata.get("source", "unknown")
            page = r.chunk.metadata.get("page", "?")
            # Trim whitespace; keep chunks compact in the prompt.
            text = " ".join(r.chunk.text.split())
            lines.append(f"[{i}] ({src}, p.{page}): {text}")
        return "\n\n".join(lines)

    @staticmethod
    def _build_citations(results: list[SearchResult]) -> list[dict]:
        return [
            {
                "index": i,
                "source": r.chunk.metadata.get("source"),
                "page": r.chunk.metadata.get("page"),
                "doc_id": r.chunk.metadata.get("doc_id"),
                "score": round(r.score, 4),
            }
            for i, r in enumerate(results, start=1)
        ]


# Module-level singleton.
retriever = Retriever()