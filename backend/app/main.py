"""
FastAPI application entry point.

What happens at startup:
  - Logging is configured.
  - Database tables are created if they don't exist (dev convenience;
    in production we use Alembic migrations).
  - LLM router is health-checked but not blocked on (the app boots even
    if a provider is down — the router has fallbacks).
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings
from app.db import Base, engine
from app.llm_router import router as llm_router
from app.routes import auth, content, documents, email, query
from app.utils.exceptions import AppException


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO" if settings.app_env == "production" else "DEBUG",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
    )


# ---------------------------------------------------------------------------
# Lifespan: startup + shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    logger.info(f"Starting app in {settings.app_env} mode")

    # Dev convenience: create_all if running locally. In prod use Alembic.
    if settings.app_env == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured (dev mode)")

    # Non-blocking health check — log status but don't fail boot.
    try:
        health = await llm_router.health()
        logger.info(f"LLM provider health: {health['providers']}")
    except Exception as e:
        logger.warning(f"LLM health check failed at boot: {e}")

    yield

    logger.info("Shutting down")
    await engine.dispose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Company AI Assistant",
    version="0.1.0",
    description="Multi-tenant AI assistant: company brain + multi-agent workflows.",
    lifespan=lifespan,
)

# CORS — wide open in dev; locked down in prod via env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env != "production" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handler — all AppException subclasses become clean JSON
# ---------------------------------------------------------------------------
@app.exception_handler(AppException)
async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/llm", tags=["meta"])
async def health_llm() -> dict:
    """Provider liveness + circuit-breaker state."""
    return await llm_router.health()


# ---------------------------------------------------------------------------
# Mount route modules
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(content.router)
app.include_router(email.router)