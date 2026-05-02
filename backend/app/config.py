"""
Centralized application configuration.

All env vars are validated and typed here. Import `settings` anywhere
in the app — never read os.environ directly.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- Core ----------
    app_env: Literal["development", "staging", "production"] = "development"
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 1 day

    # ---------- Database ----------
    database_url: str = "postgresql+asyncpg://neuroscale:Dishant_2015@localhost:5432/aiassistant"

    # ---------- LLM Providers ----------
    groq_api_key: str = ""
    groq_model_fast: str = "llama-3.1-8b-instant"          # writing, drafting
    groq_model_reasoning: str = "llama-3.3-70b-versatile"  # strategy, planning

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"                      # internal/sensitive

    # ---------- AWS ----------
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_docs: str = "companyaidocs"
    ses_sender_email: str = "admin@nskailabs.com"

    # ---------- RAG ----------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384  # MUST match the model above
    faiss_index_dir: Path = Path("./data/faiss")
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    retrieval_mmr_lambda: float = 0.5  # 0=max diversity, 1=max relevance

    # ---------- Limits ----------
    max_upload_mb: int = 25


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of re-instantiating."""
    return Settings()


settings = get_settings()