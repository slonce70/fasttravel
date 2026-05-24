"""Prometheus exporter for the bot — same shape as scheduler.metrics.

Two metric families:

  * `fasttravel_bot_messages_total{handler, outcome}` — Counter, every
    Telegram update that hits a handler is tagged. handler = router name
    ("commands", "search_wizard", …); outcome = "ok" / "error" / "filtered".

  * `fasttravel_bot_callback_latency_seconds{handler}` — Histogram, time
    inside the handler. Lets us alert on a wizard step that starts taking
    > 1s p95 (usually an API slowdown).

The middleware in `src.infra.middleware` wires both around every handler
without touching individual handler code.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

from src.infra.logging import get_logger

log = get_logger(__name__)

REGISTRY = CollectorRegistry()

BOT_MESSAGES = Counter(
    "fasttravel_bot_messages_total",
    "Total Telegram updates handled, by handler and outcome.",
    labelnames=("handler", "outcome"),
    registry=REGISTRY,
)

BOT_HANDLER_LATENCY = Histogram(
    "fasttravel_bot_handler_latency_seconds",
    "Wall-clock duration of bot handler invocations.",
    labelnames=("handler",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
    registry=REGISTRY,
)


def start_metrics_server(port: int) -> None:
    try:
        start_http_server(port, registry=REGISTRY)
        log.info("bot.metrics.started", port=port)
    except OSError as exc:
        log.warning("bot.metrics.bind_failed", port=port, error=str(exc))
