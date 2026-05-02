"""
FAISS-backed vectorstore with per-company namespacing.

Design
------
Each company gets its own folder:
    data/faiss/{company_id}/
        index.faiss        # FAISS binary index
        chunks.pkl         # parallel list of Chunk objects (text + metadata)

Why per-company instead of one global index with metadata filtering?
- Faster search (no post-filter scan).
- Trivial offboarding: delete the folder.
- Smaller indexes per tenant => fits in RAM easily.
- Trade-off: more files on disk. Acceptable for our scale (1k–10k companies).

We use IndexFlatIP (inner product) on normalized vectors, which is equivalent
to cosine similarity. For >1M vectors per company we'd switch to IVF/HNSW,
but flat is simpler and fine for typical company doc volumes.

Concurrency note
----------------
FAISS in-memory indexes aren't thread-safe for writes. We use an asyncio.Lock
keyed by company_id to serialize writes per tenant; reads are lock-free since
add() returns a new state and we only swap the index reference atomically.
"""
from __future__ import annotations

import asyncio
import pickle
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import faiss
import numpy as np
from loguru import logger

from app.config import settings
from app.rag.chunker import Chunk
from app.rag.embedder import embedder


class SearchResult(NamedTuple):
    chunk: Chunk
    score: float  # cosine similarity in [-1, 1]; higher is better


class CompanyVectorStore:
    """
    Manages one FAISS index per company.

    All operations are async to keep the FastAPI event loop responsive.
    The actual FAISS calls run in a thread pool.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir: Path = base_dir or settings.faiss_index_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: company_id -> (faiss_index, chunks_list)
        self._cache: dict[str, tuple[faiss.Index, list[Chunk]]] = {}

        # Per-company write locks to prevent concurrent index corruption.
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _company_dir(self, company_id: str) -> Path:
        d = self.base_dir / company_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index_path(self, company_id: str) -> Path:
        return self._company_dir(company_id) / "index.faiss"

    def _chunks_path(self, company_id: str) -> Path:
        return self._company_dir(company_id) / "chunks.pkl"

    # ------------------------------------------------------------------
    # Load / create
    # ------------------------------------------------------------------
    def _load_or_create_sync(self, company_id: str) -> tuple[faiss.Index, list[Chunk]]:
        idx_path = self._index_path(company_id)
        chunks_path = self._chunks_path(company_id)

        if idx_path.exists() and chunks_path.exists():
            index = faiss.read_index(str(idx_path))
            with open(chunks_path, "rb") as f:
                chunks = pickle.load(f)
            logger.info(
                f"Loaded FAISS index for {company_id} "
                f"({index.ntotal} vectors, {len(chunks)} chunks)"
            )
            return index, chunks

        # Brand-new company: empty IndexFlatIP.
        index = faiss.IndexFlatIP(settings.embedding_dim)
        chunks: list[Chunk] = []
        logger.info(f"Created new FAISS index for {company_id}")
        return index, chunks

    async def _get(self, company_id: str) -> tuple[faiss.Index, list[Chunk]]:
        if company_id not in self._cache:
            self._cache[company_id] = await asyncio.to_thread(
                self._load_or_create_sync, company_id
            )
        return self._cache[company_id]

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    def _persist_sync(
        self, company_id: str, index: faiss.Index, chunks: list[Chunk]
    ) -> None:
        faiss.write_index(index, str(self._index_path(company_id)))
        with open(self._chunks_path(company_id), "wb") as f:
            pickle.dump(chunks, f)

    async def _persist(
        self, company_id: str, index: faiss.Index, chunks: list[Chunk]
    ) -> None:
        await asyncio.to_thread(self._persist_sync, company_id, index, chunks)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def add_chunks(self, company_id: str, chunks: list[Chunk]) -> int:
        """
        Embed and add chunks to a company's index. Returns count added.
        Persisted to disk before returning.
        """
        if not chunks:
            return 0

        async with self._locks[company_id]:
            # 1. Embed
            vectors = await embedder.embed([c.text for c in chunks])

            # 2. Add to index (in thread pool — FAISS releases the GIL)
            index, existing = await self._get(company_id)

            def _add():
                index.add(vectors)
                existing.extend(chunks)

            await asyncio.to_thread(_add)

            # 3. Persist
            await self._persist(company_id, index, existing)

            logger.info(
                f"Added {len(chunks)} chunks to {company_id} "
                f"(total: {index.ntotal})"
            )
            return len(chunks)

    async def search(
        self,
        company_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """Plain similarity search."""
        top_k = top_k or settings.retrieval_top_k
        index, chunks = await self._get(company_id)
        if index.ntotal == 0:
            return []

        query_vec = await embedder.embed_one(query)
        query_vec = query_vec.reshape(1, -1)

        def _search():
            return index.search(query_vec, min(top_k, index.ntotal))

        scores, indices = await asyncio.to_thread(_search)

        results: list[SearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:  # FAISS returns -1 when fewer than top_k results exist
                continue
            results.append(SearchResult(chunk=chunks[idx], score=float(score)))
        return results

    async def search_mmr(
        self,
        company_id: str,
        query: str,
        top_k: int | None = None,
        fetch_k: int = 20,
        lambda_mult: float | None = None,
    ) -> list[SearchResult]:
        """
        Maximal Marginal Relevance search.

        Reduces redundancy in retrieved chunks — useful when a company has
        uploaded many similar docs (e.g. multiple blog posts saying the same
        thing). We fetch fetch_k candidates, then greedily pick top_k that
        balance relevance to the query against diversity from already-picked.
        """
        top_k = top_k or settings.retrieval_top_k
        lambda_mult = (
            lambda_mult if lambda_mult is not None else settings.retrieval_mmr_lambda
        )

        index, chunks = await self._get(company_id)
        if index.ntotal == 0:
            return []

        query_vec = await embedder.embed_one(query)
        query_vec_2d = query_vec.reshape(1, -1)

        def _search():
            return index.search(query_vec_2d, min(fetch_k, index.ntotal))

        scores, indices = await asyncio.to_thread(_search)
        candidate_indices = [int(i) for i in indices[0] if i != -1]
        if not candidate_indices:
            return []

        # Reconstruct candidate vectors from the index for diversity calc.
        # IndexFlatIP supports .reconstruct().
        def _reconstruct():
            return np.vstack([index.reconstruct(i) for i in candidate_indices])

        cand_vecs = await asyncio.to_thread(_reconstruct)

        # Greedy MMR
        selected_local: list[int] = []  # indices into candidate_indices
        candidate_to_query_sim = (cand_vecs @ query_vec).flatten()  # shape (fetch_k,)

        while len(selected_local) < top_k and len(selected_local) < len(candidate_indices):
            best_local = -1
            best_score = -np.inf
            for local_i in range(len(candidate_indices)):
                if local_i in selected_local:
                    continue
                relevance = candidate_to_query_sim[local_i]
                if not selected_local:
                    diversity_penalty = 0.0
                else:
                    sel_vecs = cand_vecs[selected_local]
                    diversity_penalty = float(np.max(sel_vecs @ cand_vecs[local_i]))
                mmr = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
                if mmr > best_score:
                    best_score = mmr
                    best_local = local_i
            if best_local == -1:
                break
            selected_local.append(best_local)

        return [
            SearchResult(
                chunk=chunks[candidate_indices[i]],
                score=float(candidate_to_query_sim[i]),
            )
            for i in selected_local
        ]

    async def delete_company(self, company_id: str) -> None:
        """Hard delete — removes the folder and clears the cache."""
        async with self._locks[company_id]:
            self._cache.pop(company_id, None)
            company_dir = self._company_dir(company_id)
            if company_dir.exists():
                for f in company_dir.iterdir():
                    f.unlink()
                company_dir.rmdir()
            logger.info(f"Deleted vectorstore for {company_id}")

    async def stats(self, company_id: str) -> dict:
        """Quick health check / dashboard metrics."""
        index, chunks = await self._get(company_id)
        unique_docs = len({c.metadata.get("doc_id") for c in chunks})
        return {
            "company_id": company_id,
            "vector_count": index.ntotal,
            "chunk_count": len(chunks),
            "document_count": unique_docs,
        }


# Module-level singleton.
vectorstore = CompanyVectorStore()