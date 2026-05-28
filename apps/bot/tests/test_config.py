"""Production configuration safety checks for the Telegram bot."""

from __future__ import annotations

import pytest

from src.config import Settings


def test_dev_allows_unconfigured_bot() -> None:
    settings = Settings(_env_file=None, environment="dev")

    settings.assert_prod_secrets()


def test_default_public_channel_link_points_to_live_channel() -> None:
    settings = Settings(_env_file=None)

    assert settings.public_channel_link == "https://t.me/fasttravel_deals"


def test_public_site_url_has_no_unsafe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.public_site_url is None
    assert settings.has_public_site is False


def test_prod_rejects_default_database_url() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id="-1009999999999",
        alertmanager_webhook_secret="abc123",
    )

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.assert_prod_secrets()


def test_prod_requires_telegram_credentials() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token=None,
        telegram_channel_id=None,
        alertmanager_webhook_secret="abc123",
    )

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN.*TELEGRAM_CHANNEL_ID"):
        settings.assert_prod_secrets()


def test_prod_requires_alertmanager_webhook_secret_when_webhook_enabled() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id="-1009999999999",
        alert_webhook_enabled=True,
        alertmanager_webhook_secret=None,
    )

    with pytest.raises(RuntimeError, match="ALERTMANAGER_WEBHOOK_SECRET"):
        settings.assert_prod_secrets()


def test_prod_skips_webhook_secret_when_webhook_disabled() -> None:
    # With the AlertManager webhook off (the $0 single-VM default), prod does
    # not require the secret — nothing posts to the listener.
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id="-1009999999999",
        alert_webhook_enabled=False,
        alertmanager_webhook_secret=None,
    )

    settings.assert_prod_secrets()


def test_prod_requires_separate_alerts_chat_id() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id=None,
        alertmanager_webhook_secret="abc123",
    )

    with pytest.raises(RuntimeError, match="TELEGRAM_ALERTS_CHAT_ID"):
        settings.assert_prod_secrets()


def test_prod_rejects_alerts_chat_equal_to_public_channel() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id="-1003825850110",
        alertmanager_webhook_secret="abc123",
    )

    with pytest.raises(RuntimeError, match="TELEGRAM_ALERTS_CHAT_ID_MUST_DIFFER"):
        settings.assert_prod_secrets()


def test_prod_accepts_rotated_secrets() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
        telegram_alerts_chat_id="-1009999999999",
        alertmanager_webhook_secret="rotated-supersecret",
    )

    settings.assert_prod_secrets()
