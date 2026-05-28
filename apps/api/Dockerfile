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
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Copy only what's needed to install deps for layer caching. The build
# context is apps/ so this Dockerfile can also vendor apps/shared/.
COPY api/pyproject.toml ./
COPY api/poetry.lock* ./

# INSTALL_DEV=true switches in the [tool.poetry.group.dev.dependencies]
# (pytest, ruff, etc.) so the resulting image can run `pytest`. Default
# is `false` so prod images stay minimal. The compose `docker-compose.test.yml`
# overlay flips this on for test runs.
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        poetry install --no-root --with dev; \
    else \
        poetry install --no-root --only main; \
    fi

# ---------- Runtime stage ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# libpq for psycopg sync driver, curl for healthchecks.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app \
    && mkdir -p /app/.pytest_cache /app/.ruff_cache \
    && chown -R app:app /app/.pytest_cache /app/.ruff_cache

# Copy installed python packages from builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# pyproject.toml is required in the runtime stage so pytest picks up
# asyncio_mode=auto and markers config when the image is run under the
# test image (api-test in docker-compose.test.yml). Prod runtime ignores it.
COPY --chown=app:app api/pyproject.toml ./

# App source
COPY --chown=app:app api/alembic.ini ./
COPY --chown=app:app api/migrations/ ./migrations/
COPY --chown=app:app api/src/ ./src/
COPY --chown=app:app shared/ ./shared/
# One-shot bootstrap / maintenance scripts. Not imported by src/ —
# invoked explicitly as `python -m scripts.<name>`.
COPY --chown=app:app api/scripts/ ./scripts/
# Tests are always copied so the prod image and the test image differ
# only by dev deps (controlled by INSTALL_DEV). Adds ~30KB to the image,
# but means the `api-test` service can run pytest without bind-mounting
# source into the container.
COPY --chown=app:app api/tests/ ./tests/

USER app

EXPOSE 8000

# NOTE: we deliberately do NOT run `alembic upgrade head` in CMD.
# Migrations are applied as a one-shot:
#   docker compose run --rm api alembic upgrade head
# This keeps prod restarts safe (no surprise schema changes on container churn).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
