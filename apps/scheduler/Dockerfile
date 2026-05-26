# Multi-stage build. Final image is ARM64-compatible (Oracle Ampere A1).
#
# IMPORTANT: this Dockerfile is built with build context = ./apps (one level
# up from this file). See `docker-compose.yml` `scheduler.build.context`.

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

# INSTALL_DEV=true pulls in dev deps (pytest, fakeredis) so the image
# can run the test suite. Flipped on by docker-compose.test.yml only.
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

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# pyproject.toml in runtime so pytest picks up asyncio_mode=auto when
# the image runs under the test overlay (docker-compose.test.yml).
COPY --chown=app:app scheduler/pyproject.toml ./

# App source for scheduler.
COPY --chown=app:app scheduler/src/ ./src/
COPY --chown=app:app scheduler/scripts/ ./scripts/
COPY --chown=app:app scheduler/tests/ ./tests/

# Shared Python packages used by both bot and scheduler (Telegram publisher,
# helpers). Lives in apps/shared/ at the repo root; PYTHONPATH=/app means
# `from shared.publishers.broadcast import ...` resolves here.
COPY --chown=app:app shared/ ./shared/

USER app

CMD ["python", "-m", "src.main"]
