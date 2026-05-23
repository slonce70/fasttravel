# Multi-stage build. Final image is ARM64-compatible (Oracle Ampere A1).
#
# IMPORTANT: this Dockerfile is built with build context = ./apps (one level
# up from this file) so it can COPY the shared
# `apps/bot/src/publishers/broadcast.py` library that the post_deals job
# depends on. See `docker-compose.yml` `scheduler.build.context`.

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

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Build context is ./apps so paths are prefixed with the package name.
COPY scheduler/pyproject.toml ./
COPY scheduler/poetry.lock* ./

RUN poetry install --no-root --only main

# ---------- Runtime stage ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# App source for scheduler.
COPY --chown=app:app scheduler/src/ ./src/
COPY --chown=app:app scheduler/tests/ ./tests/

# Shared Telegram publisher lib from apps/bot/. We mount it into the
# scheduler's import path as src.publishers — kept in a sibling subpackage
# so its only import shape is `from src.publishers.broadcast import ...`
# both in the scheduler and (later) in the bot service.
COPY --chown=app:app bot/src/publishers/ ./src/publishers/

USER app

CMD ["python", "-m", "src.main"]
