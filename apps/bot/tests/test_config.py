"""Production configuration safety checks for the Telegram bot."""

from __future__ import annotations

import pytest
from src.config import Settings


def test_dev_allows_unconfigured_bot() -> None:
    settings = Settings(_env_file=None, environment="dev")

    settings.assert_prod_secrets()


def test_default_public_channel_link_points_to_live_test_channel() -> None:
    settings = Settings(_env_file=None)

    assert settings.public_channel_link == "https://t.me/testtyhhh"


def test_public_site_url_has_no_unsafe_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.public_site_url is None
    assert settings.has_public_site is False


def test_prod_rejects_default_database_url() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
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
    )

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN.*TELEGRAM_CHANNEL_ID"):
        settings.assert_prod_secrets()


def test_prod_accepts_rotated_secrets() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
    )

    settings.assert_prod_secrets()
