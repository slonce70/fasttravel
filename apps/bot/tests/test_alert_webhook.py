"""Tests for the Sprint 2.3 AlertManager → Telegram bridge.

We use aiohttp's built-in test client (no real network) and stub out
the broadcast_deal call so a test never tries to reach Telegram.
"""

from __future__ import annotations

import warnings
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import src.alert_webhook as alert_webhook
from src.alert_webhook import _format_alert, build_app


@pytest.fixture(autouse=True)
def _clear_secret_env(monkeypatch):
    """The dev .env now sets ALERTMANAGER_WEBHOOK_SECRET (Sprint 2.3
    deployment). Unsetting per-test so the default-no-secret behaviour
    of the webhook is exercised; the `test_secret_required_when_env_set`
    test sets it explicitly via its own monkeypatch."""
    monkeypatch.delenv("ALERTMANAGER_WEBHOOK_SECRET", raising=False)


@pytest.fixture
def fake_bot():
    """A real-ish Bot stand-in. broadcast_deal is monkey-patched so the
    bot object's identity is all that matters."""
    return object()


def test_build_app_uses_typed_app_keys_without_warnings(fake_bot) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build_app(fake_bot, channel_id="@test_channel")

    assert not [w for w in caught if issubclass(w.category, web.NotAppKeyWarning)]


@pytest.fixture
async def client(fake_bot, monkeypatch):
    """aiohttp TestClient bound to a freshly-built app."""
    broadcast_mock = AsyncMock(return_value=12345)
    monkeypatch.setattr(alert_webhook, "broadcast_deal", broadcast_mock)
    app = build_app(fake_bot, channel_id="@test_channel")
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client, broadcast_mock
    await client.close()


# ── _format_alert pure-function tests ───────────────────────────────────


def test_format_alert_includes_name_and_severity() -> None:
    alert = {
        "status": "firing",
        "labels": {"alertname": "StaleSnapshot", "severity": "critical"},
        "annotations": {"summary": "snapshot is stale"},
    }
    text = _format_alert(alert)
    assert "StaleSnapshot" in text
    assert "critical" in text
    assert "firing" in text
    assert "stale" in text.lower()


def test_format_alert_escapes_markdown_chars() -> None:
    """Hotel-name-style content (special chars) must not break MarkdownV2."""
    alert = {
        "status": "firing",
        "labels": {"alertname": "TestAlert", "severity": "info"},
        "annotations": {"summary": "price drop (>50%)!"},
    }
    text = _format_alert(alert)
    # Special MarkdownV2 chars must be escaped
    assert "\\(" in text or "\\)" in text or "\\!" in text or "\\>" in text


def test_format_alert_handles_resolved_status() -> None:
    alert = {
        "status": "resolved",
        "labels": {"alertname": "StaleSnapshot", "severity": "critical"},
        "annotations": {"summary": "back to normal"},
    }
    text = _format_alert(alert)
    assert "resolved" in text
    assert "✅" in text  # resolved emoji


def test_format_alert_truncates_long_description() -> None:
    """Description capped so it never blows past Telegram's 4096 char limit."""
    alert = {
        "status": "firing",
        "labels": {"alertname": "TestAlert", "severity": "warning"},
        "annotations": {"summary": "s", "description": "x" * 5000},
    }
    text = _format_alert(alert)
    assert len(text) < 1000  # well under 4096
    assert "…" in text  # truncation marker


def test_format_alert_escapes_markdown_code_block_description() -> None:
    alert = {
        "status": "firing",
        "labels": {"alertname": "BrokenMarkdown", "severity": "warning"},
        "annotations": {
            "summary": "s",
            "description": r"path C:\tmp triggered `code` sample",
        },
    }

    text = _format_alert(alert)

    assert r"C:\\tmp" in text
    assert r"\`code\`" in text


def test_format_alert_handles_missing_fields() -> None:
    """Minimal payload — alertname only — should still render."""
    alert = {"status": "firing", "labels": {"alertname": "Bare"}}
    text = _format_alert(alert)
    assert "Bare" in text


# ── webhook endpoint tests ──────────────────────────────────────────────


async def test_health_endpoint_returns_200(client) -> None:
    cl, _ = client
    resp = await cl.get("/alerts/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"


async def test_posts_to_telegram_on_valid_payload(client) -> None:
    cl, broadcast = client
    payload = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "StaleSnapshot", "severity": "critical"},
                "annotations": {"summary": "snapshot stuck"},
            }
        ],
    }
    resp = await cl.post("/alerts", json=payload)
    assert resp.status == 202
    body = await resp.json()
    assert body["posted"] == 1
    assert broadcast.await_count == 1


async def test_posts_multiple_alerts_in_one_batch(client) -> None:
    cl, broadcast = client
    payload = {
        "alerts": [
            {"status": "firing", "labels": {"alertname": "A"}, "annotations": {}},
            {"status": "firing", "labels": {"alertname": "B"}, "annotations": {}},
            {"status": "resolved", "labels": {"alertname": "C"}, "annotations": {}},
        ]
    }
    resp = await cl.post("/alerts", json=payload)
    assert resp.status == 202
    body = await resp.json()
    assert body["posted"] == 3
    assert broadcast.await_count == 3


async def test_empty_alerts_list_is_accepted(client) -> None:
    cl, broadcast = client
    resp = await cl.post("/alerts", json={"alerts": []})
    assert resp.status == 202
    body = await resp.json()
    assert body["posted"] == 0
    assert broadcast.await_count == 0


async def test_rejects_invalid_json(client) -> None:
    cl, _ = client
    resp = await cl.post(
        "/alerts",
        data="not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


async def test_rejects_alerts_not_a_list(client) -> None:
    cl, _ = client
    resp = await cl.post("/alerts", json={"alerts": "wrong shape"})
    assert resp.status == 400


async def test_secret_required_when_env_set(fake_bot, monkeypatch) -> None:
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_SECRET", "supersecret-xyz")
    monkeypatch.setattr(alert_webhook, "broadcast_deal", AsyncMock())

    app = build_app(fake_bot, channel_id="@test")
    server = TestServer(app)
    cl = TestClient(server)
    await cl.start_server()
    try:
        # Without secret → 401
        resp = await cl.post("/alerts", json={"alerts": []})
        assert resp.status == 401

        # Wrong secret → 401
        resp = await cl.post(
            "/alerts",
            json={"alerts": []},
            headers={"X-Webhook-Secret": "wrong"},
        )
        assert resp.status == 401

        # Right secret → 202
        resp = await cl.post(
            "/alerts",
            json={"alerts": []},
            headers={"X-Webhook-Secret": "supersecret-xyz"},
        )
        assert resp.status == 202

        # Bearer token equivalence (AlertManager native path)
        resp = await cl.post(
            "/alerts",
            json={"alerts": []},
            headers={"Authorization": "Bearer supersecret-xyz"},
        )
        assert resp.status == 202
    finally:
        await cl.close()


async def test_prod_fails_closed_when_secret_unset(fake_bot, monkeypatch) -> None:
    """Audit #2: with no ALERTMANAGER_WEBHOOK_SECRET in prod, the webhook
    must refuse the request rather than silently accept it."""
    from src.config import Settings, get_settings

    monkeypatch.delenv("ALERTMANAGER_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(alert_webhook, "broadcast_deal", AsyncMock())

    fake_prod = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:s@postgres:5432/fasttravel",
        telegram_bot_token="123:t",
        telegram_channel_id="-100",
        alertmanager_webhook_secret=None,
    )
    monkeypatch.setattr(alert_webhook, "get_settings", lambda: fake_prod)

    app = build_app(fake_bot, channel_id="@test")
    server = TestServer(app)
    cl = TestClient(server)
    await cl.start_server()
    try:
        resp = await cl.post("/alerts", json={"alerts": []})
        assert resp.status == 503
    finally:
        await cl.close()
        get_settings.cache_clear()


async def test_no_channel_returns_202_with_note(monkeypatch) -> None:
    """Mis-configured deployment (no channel_id) shouldn't make
    AlertManager retry forever — return 202 with a note."""
    monkeypatch.setattr(alert_webhook, "broadcast_deal", AsyncMock())
    app = build_app(bot=None, channel_id=None)
    server = TestServer(app)
    cl = TestClient(server)
    await cl.start_server()
    try:
        resp = await cl.post(
            "/alerts",
            json={
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "X"},
                        "annotations": {},
                    }
                ]
            },
        )
        assert resp.status == 202
        body = await resp.json()
        assert body["posted"] == 0
        assert "no_channel" in body["note"]
    finally:
        await cl.close()


async def test_broadcast_error_returns_500(fake_bot, monkeypatch) -> None:
    """If Telegram is down, return 500 so AlertManager retries with
    its built-in backoff."""
    broadcast = AsyncMock(side_effect=RuntimeError("telegram unreachable"))
    monkeypatch.setattr(alert_webhook, "broadcast_deal", broadcast)
    app = build_app(fake_bot, channel_id="@test")
    server = TestServer(app)
    cl = TestClient(server)
    await cl.start_server()
    try:
        resp = await cl.post(
            "/alerts",
            json={
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "X"},
                        "annotations": {},
                    }
                ]
            },
        )
        assert resp.status == 500
        body = await resp.json()
        assert body["posted"] == 0
        assert len(body["errors"]) >= 1
    finally:
        await cl.close()
