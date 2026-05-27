"""aiohttp.web app that receives Prometheus AlertManager webhooks and
re-broadcasts them to the operator's Telegram channel.

Why aiohttp (not FastAPI): the bot already runs aiogram which depends
on aiohttp; adding FastAPI would pull in starlette + pydantic-fastapi
for a single endpoint. aiohttp.web is in the import graph either way.

Why a single endpoint inside the bot process: AlertManager's webhook
receiver is fire-and-forget HTTP POST → 200 OK. Splitting it into its
own service would mean another container, another Prometheus target,
another set of credentials to manage. The bot already has the Telegram
token and a connection to the channel; it's the natural place.

Endpoint:
  POST /alerts
    Body: AlertManager webhook payload (see
      https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
    Headers:
      X-Webhook-Secret: <shared secret>   if ALERTMANAGER_WEBHOOK_SECRET is set
    Returns:
      202 Accepted   on success (we may still be retrying Telegram)
      401            on bad secret
      400            on malformed body
      500            on render/broadcast error (AlertManager will retry)

Health: `GET /alerts/health` returns 200 + JSON, used by docker-compose
healthcheck.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from aiogram import Bot
from aiohttp import web

from shared.publishers.broadcast import broadcast_deal, escape_markdown_v2
from src.config import get_settings
from src.infra.logging import get_logger

log = get_logger(__name__)


# Header name used by AlertManager's `http_config.basic_auth` alternatives.
# We use a custom header to avoid wiring Basic Auth machinery — operators
# just put a long random string into `ALERTMANAGER_WEBHOOK_SECRET`.
SECRET_HEADER = "X-Webhook-Secret"


def _format_alert(alert: dict[str, Any]) -> str:
    """Render one AlertManager-format alert as a MarkdownV2 message body.

    AlertManager `alerts[]` item shape (relevant fields):
      status: 'firing' | 'resolved'
      labels: {alertname, severity, ...}
      annotations: {summary, description}
      startsAt: ISO8601
      generatorURL: link back to Prometheus
    """
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    status = alert.get("status", "unknown")
    name = labels.get("alertname", "unnamed_alert")
    severity = labels.get("severity", "info")

    emoji = {
        "firing-critical": "🚨",
        "firing-warning": "⚠️",
        "firing-info": "ℹ️",
        "resolved-critical": "✅",
        "resolved-warning": "✅",
        "resolved-info": "✅",
    }.get(f"{status}-{severity}", "🔔")

    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    parts = [
        f"{emoji} *{escape_markdown_v2(name)}*",
        f"_{escape_markdown_v2(status)} \\| {escape_markdown_v2(severity)}_",
    ]
    if summary:
        parts.append(escape_markdown_v2(summary))
    if description:
        # Description can be multiline; cap at ~600 chars so a verbose
        # alert doesn't blow past Telegram's 4096 limit.
        trimmed = description[:600] + ("…" if len(description) > 600 else "")
        parts.append(f"```\n{trimmed}\n```")
    return "\n".join(parts)


async def _alerts_handler(request: web.Request) -> web.Response:
    secret = os.getenv("ALERTMANAGER_WEBHOOK_SECRET", "")
    # Fail-closed in prod: an unset secret in prod means "anyone with
    # network reach can spoof firing alerts into the operator channel"
    # — refuse the request rather than silently accepting (audit #2).
    if not secret:
        if get_settings().is_prod:
            log.error("alert_webhook.secret_missing_in_prod")
            return web.json_response({"error": "server_misconfigured"}, status=503)
    else:
        # Accept either:
        #   X-Webhook-Secret: <secret>       (custom header, dev convenience)
        #   Authorization: Bearer <secret>   (AlertManager native, prod path)
        # so the same bot works with curl smoke tests AND with a
        # production AlertManager `authorization: credentials:` block.
        custom = request.headers.get(SECRET_HEADER, "")
        auth = request.headers.get("Authorization", "")
        bearer = auth[len("Bearer ") :].strip() if auth.startswith("Bearer ") else ""
        # compare_digest is constant-time — defends against the timing
        # side-channel a plain `!=` would expose.
        ok = hmac.compare_digest(custom, secret) or hmac.compare_digest(bearer, secret)
        if not ok:
            log.warning("alert_webhook.bad_secret")
            return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_webhook.bad_body", error=str(exc))
        return web.json_response({"error": "invalid_json"}, status=400)

    alerts = body.get("alerts") or []
    if not isinstance(alerts, list):
        return web.json_response({"error": "alerts_not_list"}, status=400)

    bot: Bot | None = request.app.get("bot")
    channel_id: str | int | None = request.app.get("channel_id")
    if bot is None or not channel_id:
        log.error(
            "alert_webhook.no_channel",
            alerts=len(alerts),
            note="bot or channel_id missing — alert lost",
        )
        # Return 202 so AlertManager doesn't loop indefinitely on a
        # mis-configured deployment.
        return web.json_response({"posted": 0, "note": "no_channel"}, status=202)

    posted = 0
    errors: list[str] = []
    for alert in alerts:
        try:
            text = _format_alert(alert)
            await broadcast_deal(bot, channel_id, text, disable_web_page_preview=True)
            posted += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("alert_webhook.broadcast_failed", error=str(exc))
            errors.append(str(exc))

    if posted > 0:
        # Log success so operators can audit who fired what via tail -f
        # without scraping AlertManager's metrics. One line per webhook
        # batch (not per alert) to keep volume sane.
        log.info(
            "alert_webhook.delivered",
            posted=posted,
            errors=len(errors),
            first_alert_name=(alerts[0].get("labels", {}) or {}).get("alertname"),
        )
    status = 202 if not errors else 500
    return web.json_response({"posted": posted, "errors": errors[:5]}, status=status)


async def _health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def build_app(bot: Bot, channel_id: str | int | None) -> web.Application:
    """Construct the aiohttp.web application.

    Storing bot + channel_id on `app` instead of module globals so tests
    can build isolated apps without polluting process state.
    """
    app = web.Application()
    app["bot"] = bot
    app["channel_id"] = channel_id
    app.router.add_post("/alerts", _alerts_handler)
    app.router.add_get("/alerts/health", _health_handler)
    return app


async def start_alert_webhook(
    bot: Bot,
    *,
    host: str = "0.0.0.0",
    port: int = 9103,
    channel_id: str | int | None = None,
) -> web.AppRunner:
    """Bind the webhook on (host, port). Returns the AppRunner so the
    caller can cleanly shut it down on SIGTERM."""
    app = build_app(bot, channel_id)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("alert_webhook.started", host=host, port=port)
    return runner
