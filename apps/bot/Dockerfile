# FastTravel Telegram bot — aiogram 3 polling.
#
# IMPORTANT: this Dockerfile is built with build context = ./apps so it can
# COPY both bot/src/ and the sibling shared/ package (Telegram publisher
# helpers shared with scheduler). See docker-compose.yml `bot.build.context`.

FROM python:3.12-slim-bookworm

WORKDIR /app

# aiogram 3 + structlog + pydantic-settings cover the bot's runtime needs.
# Pin to the same versions the scheduler resolves to so the shared publisher
# package stays binary-compatible across both services.
RUN pip install --no-cache-dir \
    aiogram==3.13.1 \
    structlog==24.4.0 \
    pydantic-settings==2.6.0 \
    pydantic==2.9.2 \
    httpx==0.27.2 \
    redis==5.2.0 \
    prometheus-client==0.21.0 \
    sentry-sdk==2.18.0 \
    "sqlalchemy[asyncio]==2.0.36" \
    asyncpg==0.30.0

# INSTALL_DEV=true layers in pytest + fakeredis so the same image can run
# the bot test suite. Default off keeps prod minimal.
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        pip install --no-cache-dir pytest==8.3.3 pytest-asyncio==0.24.0 fakeredis==2.26.1 ruff==0.7.4; \
    fi

# Bot source.
COPY bot/src/ ./src/

# Test source + pytest config (asyncio_mode=auto) — always copied so the
# prod image is identical regardless of INSTALL_DEV variant. The bot has
# no pyproject.toml, so pytest config lives in pytest.ini.
COPY bot/tests/ ./tests/
COPY bot/pytest.ini ./pytest.ini

# Shared Python packages (PYTHONPATH=/app means `from shared.publishers...`
# resolves to ./shared/publishers/).
COPY shared/ ./shared/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "src.main"]
