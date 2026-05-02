"""
RAG package.

Public interface (use these from services/agents/routes):
    - ingest_pipeline.ingest_file(...)
    - ingest_pipeline.ingest_text(...)
    - retriever.retrieve(...)
    - vectorstore.stats(...)
    - vectorstore.delete_company(...)

Internal modules (chunker, embedder) shouldn't be imported directly.
"""
from app.rag.ingest import ingest_pipeline, IngestResult
from app.rag.retriever import retriever, RetrievedContext
from app.rag.vectorstore import vectorstore, SearchResult

__all__ = [
    "ingest_pipeline",
    "IngestResult",
    "retriever",
    "RetrievedContext",
    "vectorstore",
    "SearchResult",
]