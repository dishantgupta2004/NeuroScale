"""
Ingest pipeline — the public entry point for "add this document to the brain".

This is what services/document_service.py calls after a successful upload
to S3. It coordinates:
    file bytes → chunker → vectorstore (which handles embedding internally)

Kept thin on purpose: the heavy lifting lives in chunker + vectorstore,
and this module is what gets called from agent tools or background jobs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from loguru import logger

from app.rag.chunker import chunker
from app.rag.vectorstore import vectorstore


@dataclass
class IngestResult:
    doc_id: str
    chunks_added: int
    source: str


class IngestPipeline:
    async def ingest_file(
        self,
        *,
        company_id: str,
        filename: str,
        content: bytes,
        doc_id: str | None = None,
    ) -> IngestResult:
        """
        Full pipeline for an uploaded file.

        Returns IngestResult with the (possibly newly generated) doc_id,
        which the caller should persist in the `documents` table so the
        chunks in FAISS can be linked back to a logical document.
        """
        doc_id = doc_id or str(uuid.uuid4())

        chunks = chunker.chunk_file(
            content=content,
            filename=filename,
            company_id=company_id,
            doc_id=doc_id,
        )
        if not chunks:
            logger.warning(f"No chunks produced from {filename}; skipping ingest")
            return IngestResult(doc_id=doc_id, chunks_added=0, source=filename)

        added = await vectorstore.add_chunks(company_id, chunks)
        return IngestResult(doc_id=doc_id, chunks_added=added, source=filename)

    async def ingest_text(
        self,
        *,
        company_id: str,
        text: str,
        source: str = "raw_text",
        doc_id: str | None = None,
    ) -> IngestResult:
        """For pasted text (e.g. a blog snippet) instead of a file."""
        doc_id = doc_id or str(uuid.uuid4())
        chunks = chunker.chunk_text(
            text=text, company_id=company_id, source=source, doc_id=doc_id
        )
        added = await vectorstore.add_chunks(company_id, chunks) if chunks else 0
        return IngestResult(doc_id=doc_id, chunks_added=added, source=source)


# Module-level singleton.
ingest_pipeline = IngestPipeline()