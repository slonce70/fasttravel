"""Production configuration safety checks for scheduler startup."""

from __future__ import annotations

import pytest

from src.config import Settings


def test_dev_allows_default_local_settings() -> None:
    settings = Settings(_env_file=None, environment="dev")

    settings.assert_prod_secrets()


def test_prod_rejects_default_database_url() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel",
        telegram_bot_token="123456:prod-token",
        telegram_channel_id="-1003825850110",
    )

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.assert_prod_secrets()


def test_prod_requires_telegram_when_channel_posts_are_enabled() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token=None,
        telegram_channel_id=None,
        deals_daily_cap=30,
    )

    with pytest.raises(RuntimeError, match=r"TELEGRAM_BOT_TOKEN.*TELEGRAM_CHANNEL_ID"):
        settings.assert_prod_secrets()


def test_prod_requires_telegram_when_channel_posts_are_unlimited() -> None:
    settings = Settings(
        _env_file=None,
        environment="prod",
        database_url="postgresql+asyncpg://fasttravel:secret@postgres:5432/fasttravel",
        telegram_bot_token=None,
        telegram_channel_id=None,
        deals_daily_cap=0,
    )

    with pytest.raises(RuntimeError, match=r"TELEGRAM_BOT_TOKEN.*TELEGRAM_CHANNEL_ID"):
        settings.assert_prod_secrets()
