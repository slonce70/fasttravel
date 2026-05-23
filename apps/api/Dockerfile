# Multi-stage build. Final image is ARM64-compatible (Oracle Ampere A1).
# Python 3.12 wheels for all our deps (asyncpg, pydantic-core, etc.) ship
# arm64 builds, so no compilation needed at install time.

# ---------- Builder stage ----------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# System deps needed only at build time for any wheels we might compile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Copy only what's needed to install deps for layer caching.
COPY pyproject.toml ./
# Note: in a real build we'd also copy poetry.lock for reproducibility.
# It's generated on first `poetry install` and should be committed afterwards.
COPY poetry.lock* ./

# Install runtime deps only (no dev).
RUN poetry install --no-root --only main

# ---------- Runtime stage ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# libpq for psycopg sync driver, curl for healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

# Copy installed python packages from builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# App source
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app src/ ./src/
# One-shot bootstrap / maintenance scripts (e.g. scripts/seed_demo.py).
# Not imported by src/ — invoked as `python -m scripts.<name>`.
COPY --chown=app:app scripts/ ./scripts/

USER app

EXPOSE 8000

# NOTE: we deliberately do NOT run `alembic upgrade head` in CMD.
# Migrations are applied as a one-shot:
#   docker compose run --rm api alembic upgrade head
# This keeps prod restarts safe (no surprise schema changes on container churn).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
