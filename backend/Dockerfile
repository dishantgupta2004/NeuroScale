# syntax=docker/dockerfile:1.7
# ============================================================================
# Backend Dockerfile — multi-stage build.
#
# Stage 1 (builder): installs deps into a venv. Heavy tooling lives here.
# Stage 2 (runtime): copies the venv only, drops to a non-root user.
#
# Why multi-stage:
#   - Final image is ~600MB instead of ~1.5GB.
#   - No compilers / build tools in production.
#   - Faster security scanning (smaller surface).
# ============================================================================
ARG PYTHON_VERSION=3.11

# --------------------------------------------------------------------------
# Stage 1: builder
# --------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for native packages (faiss, sentence-transformers wheels normally
# avoid this, but psycopg2 etc. sometimes need it).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create venv inside /opt — easy to copy as a single dir.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

# Install — pip cache mount keeps repeat builds fast.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# --------------------------------------------------------------------------
# Stage 2: runtime
# --------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOME=/app

# curl for the HEALTHCHECK below; libgomp1 needed by faiss-cpu at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (UID 1000 by convention).
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m -s /bin/bash app

COPY --from=builder /opt/venv /opt/venv

WORKDIR ${APP_HOME}
COPY --chown=app:app . .

# FAISS index dir + scratch — must be writable.
RUN mkdir -p ${APP_HOME}/data/faiss && chown -R app:app ${APP_HOME}/data

USER app

EXPOSE 8000

# Backend health endpoint we built in Phase 5.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Production: no --reload. Workers tuned to 2 (FAISS holds RAM, more workers
# means more index copies in memory). For high-traffic deployments, scale
# horizontally with multiple containers behind nginx.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
