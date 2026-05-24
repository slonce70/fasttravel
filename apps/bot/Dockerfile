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
    pydantic==2.9.2

# Bot source.
COPY bot/src/ ./src/

# Shared Python packages (PYTHONPATH=/app means `from shared.publishers...`
# resolves to ./shared/publishers/).
COPY shared/ ./shared/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "src.main"]
