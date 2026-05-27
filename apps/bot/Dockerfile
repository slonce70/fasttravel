# FastTravel Telegram bot — aiogram 3 polling + AlertManager webhook.
#
# IMPORTANT: build context = ./apps so this Dockerfile can COPY both
# bot/src/ and the sibling shared/ package (Telegram publisher helpers
# shared with scheduler). See docker-compose.yml `bot.build.context`.
#
# Multi-stage build (audit #8 sprint): builder installs deps via Poetry
# using the same lockfile pattern as api/scheduler; runtime stage strips
# build toolchain and runs as a non-root user with a HEALTHCHECK.

# ---------- Builder stage ----------
FROM python:3.14-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Copy only what Poetry needs to resolve deps, for max layer caching.
COPY bot/pyproject.toml ./
COPY bot/poetry.lock* ./

ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        poetry install --no-root --with dev; \
    else \
        poetry install --no-root --only main; \
    fi

# ---------- Runtime stage ----------
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Runtime libs:
#   - libpq5 for asyncpg / psycopg shared transport.
#   - curl for the docker HEALTHCHECK against the /alerts/health endpoint.
# Create the non-root user that the app process will run as.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

# Copy installed Python packages + console scripts from the builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# pyproject.toml needed at runtime so pytest picks up asyncio_mode=auto
# when the image is invoked under the test overlay.
COPY --chown=app:app bot/pyproject.toml ./

# Bot source. PYTHONPATH=/app lets `import src…` and `import shared…`
# resolve flat from the WORKDIR.
COPY --chown=app:app bot/src/ ./src/
COPY --chown=app:app bot/tests/ ./tests/
COPY --chown=app:app bot/pytest.ini ./pytest.ini

# Shared Python packages (apps/shared/publishers/broadcast.py etc).
# Same path inside the container as in the repo so PYTHONPATH stays simple.
COPY --chown=app:app shared/ ./shared/

USER app

# Healthcheck targets the /alerts webhook's GET /alerts/health endpoint
# (port 9103, exposed inside the fasttravel docker network only).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:9103/alerts/health || exit 1

CMD ["python", "-m", "src.main"]
