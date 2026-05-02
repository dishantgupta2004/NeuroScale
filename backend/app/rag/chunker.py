"""
Document chunking layer.

Responsibilities
----------------
- Detect file type and extract raw text + per-page/section metadata.
- Recursively split text into overlapping chunks of ~chunk_size chars.
- Attach metadata to every chunk (source, doc_id, page, chunk_index)
  so the retriever can later return citations.

Why recursive char splitting (not token-based)?
- Token-based splitters require a tokenizer call per chunk; for a 100-page
  PDF that is wasteful. Char-based with a slightly conservative chunk_size
  (800 chars ≈ 200 tokens for English) keeps us comfortably below model
  context limits while staying fast.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from app.config import settings


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    """A single chunk of text plus metadata that travels with it through the
    embedder → vectorstore → retriever pipeline."""
    text: str
    metadata: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        # Stable id = doc_id + chunk_index, useful for upserts / dedup.
        return f"{self.metadata.get('doc_id', 'unk')}::{self.metadata.get('chunk_index', 0)}"


# ---------------------------------------------------------------------------
# File-type extractors
# ---------------------------------------------------------------------------
def _extract_pdf(content: bytes) -> list[tuple[str, dict]]:
    """Return list of (text, page_metadata) per page."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((text, {"page": i + 1}))
    return pages


def _extract_docx(content: bytes) -> list[tuple[str, dict]]:
    from docx import Document

    doc = Document(io.BytesIO(content))
    # docx has no real page concept — treat whole doc as one "page".
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(text, {"page": 1})] if text else []


def _extract_txt(content: bytes) -> list[tuple[str, dict]]:
    text = content.decode("utf-8", errors="ignore").strip()
    return [(text, {"page": 1})] if text else []


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
    ".md": _extract_txt,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
class DocumentChunker:
    """Stateless chunker — instantiate once and reuse."""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size or settings.chunk_size,
            chunk_overlap=chunk_overlap or settings.chunk_overlap,
            # Order matters: try paragraph break, then line, then sentence, then word.
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

    def chunk_file(
        self,
        *,
        content: bytes,
        filename: str,
        company_id: str,
        doc_id: str | None = None,
    ) -> list[Chunk]:
        """
        Split a file into chunks.

        Parameters
        ----------
        content : raw file bytes (already read from upload or S3).
        filename : original filename, used for extension detection + provenance.
        company_id : tenant scoping (every chunk carries this).
        doc_id : stable id for the source document; generated if not provided.
        """
        ext = Path(filename).suffix.lower()
        extractor = _EXTRACTORS.get(ext)
        if extractor is None:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {list(_EXTRACTORS)}"
            )

        doc_id = doc_id or str(uuid.uuid4())
        pages = extractor(content)
        if not pages:
            logger.warning(f"No text extracted from {filename}")
            return []

        chunks: list[Chunk] = []
        global_idx = 0
        for page_text, page_meta in pages:
            for piece in self.splitter.split_text(page_text):
                piece = piece.strip()
                if not piece:
                    continue
                chunks.append(
                    Chunk(
                        text=piece,
                        metadata={
                            "company_id": company_id,
                            "doc_id": doc_id,
                            "source": filename,
                            "chunk_index": global_idx,
                            **page_meta,
                        },
                    )
                )
                global_idx += 1

        logger.info(
            f"Chunked {filename} → {len(chunks)} chunks "
            f"(company={company_id}, doc_id={doc_id})"
        )
        return chunks

    def chunk_text(
        self,
        *,
        text: str,
        company_id: str,
        source: str = "raw_text",
        doc_id: str | None = None,
    ) -> list[Chunk]:
        """For programmatic ingestion — e.g. pasting a blog into the system."""
        doc_id = doc_id or str(uuid.uuid4())
        chunks = []
        for i, piece in enumerate(self.splitter.split_text(text)):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                Chunk(
                    text=piece,
                    metadata={
                        "company_id": company_id,
                        "doc_id": doc_id,
                        "source": source,
                        "chunk_index": i,
                        "page": 1,
                    },
                )
            )
        return chunks


# Module-level singleton — chunker is stateless and cheap to share.
chunker = DocumentChunker()