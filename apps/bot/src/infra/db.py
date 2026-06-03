"""Direct DB access for the bot — telegram_subscribers + subscriber_filters.

The bot is the canonical owner of these two tables (no API endpoint
exposes them yet, and we'd rather not add CSRF/auth surface area for
internal-use writes). Connection pool is small (3) — bot rarely makes
DB calls outside of subscribe / profile flows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings
from src.infra.logging import get_logger

log = get_logger(__name__)


_ENGINE: AsyncEngine | None = None
_SESSIONMAKER: async_sessionmaker[AsyncSession] | None = None


def _build_url() -> str:
    """Resolve the Postgres URL from typed settings."""
    return get_settings().database_url


def get_engine() -> AsyncEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            _build_url(),
            pool_size=3,
            max_overflow=2,
            pool_pre_ping=True,
        )
    return _ENGINE


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SESSIONMAKER
    if _SESSIONMAKER is None:
        _SESSIONMAKER = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _SESSIONMAKER


async def close_engine() -> None:
    global _ENGINE
    if _ENGINE is not None:
        await _ENGINE.dispose()
        _ENGINE = None


# ---------------------------------------------------------------------------
# Subscribers — upsert on every interaction so we have a row for every user.
# ---------------------------------------------------------------------------


async def ensure_subscriber(chat_id: int, username: str | None = None) -> None:
    """Idempotent INSERT — used by `/start` and any DB-writing flow to
    guarantee the FK target exists before we touch subscriber_filters."""
    async with get_session_factory()() as db:
        await db.execute(
            text(
                """
                INSERT INTO telegram_subscribers (chat_id, username)
                VALUES (:chat_id, :username)
                ON CONFLICT (chat_id) DO UPDATE
                  SET username = EXCLUDED.username,
                      last_active = NOW()
                """
            ),
            {"chat_id": chat_id, "username": username},
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Subscriber filters CRUD
# ---------------------------------------------------------------------------


async def find_subscription(
    chat_id: int,
    *,
    country_iso2: str,
    max_price_uah: int | None,
    min_stars: int | None,
    meal_plan: str | None,
) -> int | None:
    """Return the id of an existing subscription with the same natural key,
    or ``None`` if there isn't one.

    The natural key is (chat_id, country_iso2, max_price_uah, min_stars,
    meal_plan). The last three are NULL for every "no limit" subscription —
    the common case — so we compare them with ``IS NOT DISTINCT FROM`` rather
    than ``=`` (which never matches NULL). Country is upper-cased to match how
    `add_subscription` stores it.

    Conservative dedup: read-only, no schema change, no UNIQUE constraint.
    """
    async with get_session_factory()() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id
                    FROM telegram_subscriber_filters
                    WHERE chat_id = :chat_id
                      AND country_iso2 = :country
                      AND max_price_uah IS NOT DISTINCT FROM :max_price
                      AND min_stars     IS NOT DISTINCT FROM :stars
                      AND meal_plan     IS NOT DISTINCT FROM :meal
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {
                    "chat_id": chat_id,
                    "country": country_iso2.upper(),
                    "max_price": max_price_uah,
                    "stars": min_stars,
                    "meal": meal_plan,
                },
            )
        ).first()
    return int(row[0]) if row is not None else None


async def add_subscription(
    chat_id: int,
    *,
    country_iso2: str,
    max_price_uah: int | None,
    min_stars: int | None,
    meal_plan: str | None,
) -> int:
    """Returns the new filter id."""
    async with get_session_factory()() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO telegram_subscriber_filters
                  (chat_id, country_iso2, max_price_uah, min_stars, meal_plan)
                VALUES (:chat_id, :country, :max_price, :stars, :meal)
                RETURNING id
                """
            ),
            {
                "chat_id": chat_id,
                "country": country_iso2.upper(),
                "max_price": max_price_uah,
                "stars": min_stars,
                "meal": meal_plan,
            },
        )
        new_id = int(result.scalar_one())
        await db.commit()
        return new_id


async def list_subscriptions(chat_id: int) -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, country_iso2, max_price_uah, min_stars, meal_plan, is_active
                    FROM telegram_subscriber_filters
                    WHERE chat_id = :chat_id
                    ORDER BY created_at DESC
                    """
                ),
                {"chat_id": chat_id},
            )
        ).all()
    return [dict(r._mapping) for r in rows]  # noqa: SLF001 — Row → dict


async def delete_subscription(chat_id: int, sub_id: int) -> bool:
    """Hard delete — same effect as is_active=false but cleaner table.
    Returns True if a row was removed."""
    async with get_session_factory()() as db:
        result = await db.execute(
            text(
                """
                DELETE FROM telegram_subscriber_filters
                WHERE chat_id = :chat_id AND id = :id
                """
            ),
            {"chat_id": chat_id, "id": sub_id},
        )
        await db.commit()
        return cast("CursorResult[Any]", result).rowcount > 0


async def get_last_notification(chat_id: int) -> datetime | None:
    """Read-only: the timestamp of the most recent personal alert sent to
    this user, or ``None`` if they've never been alerted.

    The notification ledger (`telegram_filter_notifications`, migration 019)
    is keyed by `filter_id`, not `chat_id`, so we join through
    `telegram_subscriber_filters` to scope by user. Covered by the
    `ix_tfn_filter_sent_at (filter_id, sent_at DESC)` index. No write, no
    schema change — purely informational for the profile hub.
    """
    async with get_session_factory()() as db:
        result = await db.execute(
            text(
                """
                SELECT MAX(n.sent_at)
                FROM telegram_filter_notifications n
                JOIN telegram_subscriber_filters f ON f.id = n.filter_id
                WHERE f.chat_id = :chat_id
                """
            ),
            {"chat_id": chat_id},
        )
        value = result.scalar()
    return value if isinstance(value, datetime) else None


async def delete_all_user_data(chat_id: int) -> None:
    """GDPR right-to-be-forgotten — wipes subscriber + filters cascade."""
    async with get_session_factory()() as db:
        await db.execute(
            text("DELETE FROM telegram_subscribers WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        )
        await db.commit()
