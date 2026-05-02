"""
Document service.

Owns the upload → ingest workflow:

    POST /upload-doc
        ├─ create Document row (status=pending)
        ├─ (later: write to S3 — Phase 6)
        ├─ run RAG ingest pipeline
        ├─ update Document row (status=ready, chunk_count=...)
        └─ return DocumentResponse

We do the ingest synchronously inside the request right now. For large
files we'd queue this to a background worker (Phase 8 territory). The
service interface stays the same either way.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.tables import Document
from app.models.document import (
    DocumentListResponse,
    DocumentResponse,
    IngestStatsResponse,
)
from app.rag import ingest_pipeline, vectorstore
from app.services.s3_service import s3_service
from app.utils.exceptions import NotFoundError, UpstreamError, ValidationError


_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class DocumentService:
    async def upload(
        self,
        db: AsyncSession,
        *,
        company_id: str,
        user_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentResponse:
        # 1. Validate
        ext = self._get_extension(filename)
        if ext not in _ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file type {ext}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}"
            )

        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.max_upload_mb:
            raise ValidationError(
                f"File too large ({size_mb:.1f}MB). Max: {settings.max_upload_mb}MB"
            )

        # 2. Create row in "pending" state. If ingest fails, this row sticks
        #    around with status=failed so the user sees what happened.
        doc = Document(
            company_id=company_id,
            uploaded_by_user_id=user_id,
            filename=filename,
            file_size_bytes=len(content),
            content_type=content_type,
            status="ingesting",
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        # 3. Mirror to S3 first. S3 is the source of truth for re-indexing,
        #    so if this fails we don't proceed to FAISS — there'd be no way
        #    to rebuild the chunks later. We DO mark the row failed so the
        #    user sees what happened.
        try:
            doc.s3_key = await s3_service.upload_document(
                company_id=company_id,
                doc_id=doc.id,
                filename=filename,
                content=content,
                content_type=content_type,
            )
            await db.commit()
        except UpstreamError as e:
            logger.error(f"S3 mirror failed for {filename}: {e}")
            doc.status = "failed"
            doc.error = f"S3 upload failed: {str(e)[:1900]}"
            await db.commit()
            await db.refresh(doc)
            return DocumentResponse.model_validate(doc)

        # 4. Run ingest pipeline. doc.id is the canonical doc_id everywhere.
        try:
            result = await ingest_pipeline.ingest_file(
                company_id=company_id,
                filename=filename,
                content=content,
                doc_id=doc.id,
            )
            doc.chunk_count = result.chunks_added
            doc.status = "ready" if result.chunks_added > 0 else "failed"
            if result.chunks_added == 0:
                doc.error = "No text could be extracted from this file"
        except Exception as e:
            logger.exception(f"Ingest failed for {filename}")
            doc.status = "failed"
            doc.error = str(e)[:1990]   # column is 2000 chars

        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)

    async def list_for_company(
        self, db: AsyncSession, *, company_id: str
    ) -> DocumentListResponse:
        r = await db.execute(
            select(Document)
            .where(Document.company_id == company_id)
            .order_by(Document.created_at.desc())
        )
        docs = list(r.scalars())
        return DocumentListResponse(
            documents=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        )

    async def delete(
        self, db: AsyncSession, *, company_id: str, document_id: str
    ) -> None:
        """Delete the metadata row + S3 object. Note: this does NOT remove
        the chunks from FAISS — that would require rebuilding the index.
        For now, deleted documents leak their chunks until the next full
        reindex. TODO: add a `tombstone` filter on retrieval."""
        r = await db.execute(
            select(Document).where(
                Document.id == document_id, Document.company_id == company_id
            )
        )
        doc = r.scalar_one_or_none()
        if doc is None:
            raise NotFoundError("Document not found")

        # Best-effort S3 cleanup — don't block row deletion if S3 fails.
        if doc.s3_key:
            await s3_service.delete_document(doc.s3_key)

        await db.delete(doc)
        await db.commit()

    async def stats(
        self, db: AsyncSession, *, company_id: str
    ) -> IngestStatsResponse:
        r = await db.execute(
            select(Document).where(Document.company_id == company_id)
        )
        docs = list(r.scalars())
        chunk_total = sum(d.chunk_count for d in docs)
        vs_stats = await vectorstore.stats(company_id)
        return IngestStatsResponse(
            company_id=company_id,
            document_count=len(docs),
            chunk_count=chunk_total,
            vector_count=vs_stats["vector_count"],
        )

    @staticmethod
    def _get_extension(filename: str) -> str:
        idx = filename.rfind(".")
        return filename[idx:].lower() if idx != -1 else ""


document_service = DocumentService()