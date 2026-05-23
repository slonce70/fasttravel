# Minimal stub. Full implementation lives in a follow-up task.
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir structlog==24.4.0

COPY src/ ./src/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "src.main"]
