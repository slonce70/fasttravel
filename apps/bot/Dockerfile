# Minimal bot stub. Full aiogram-3 implementation lands in a follow-up task.
#
# IMPORTANT: this Dockerfile is built with build context = ./apps so it can
# COPY both bot/src/ and the sibling shared/ package (Telegram publisher
# helpers used by both bot and scheduler). See docker-compose.yml
# `bot.build.context`.

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir structlog==24.4.0

# Bot source.
COPY bot/src/ ./src/

# Shared Python packages (PYTHONPATH=/app means `from shared.publishers...`
# resolves to ./shared/publishers/).
COPY shared/ ./shared/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "src.main"]
