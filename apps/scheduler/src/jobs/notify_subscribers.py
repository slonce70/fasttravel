"""notify_subscribers — one-to-one Telegram pings for matching deals.

Runs after `detect_deals` on every hourly tick. For each subscriber
filter, finds one best matching deal that:
  - was detected in the same fresh window the public channel accepts
  - has not already been sent for that filter
  - matches country, max_price, min_stars
After each successful send we write `(filter_id, deal_id)` to
`telegram_filter_notifications`, so re-runs stay idempotent without a
single scalar cursor suppressing lower-id deals.

Throttling: 2 seconds between sends (Telegram's 30 msg/sec soft cap is
30 per *bot*, but per-chat the recommended cap is ~1 msg/sec). Cap of
50 sends per run so a slow Telegram day can't queue up an avalanche.

Token absence (TELEGRAM_BOT_TOKEN unset) is silently skipped — same
contract as post_deals.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from shared.deal_rendering import render_deal_price_semantics
from shared.deal_signals import get_deal_signal_copy
from shared.meal_plans import meal_plan_match_sql
from shared.publishers.broadcast import escape_markdown_v2, make_bot
from shared.site_urls import public_hotel_url
from shared.text_uk import (
    format_date_short,
    format_meal_plan,
    format_nights,
    format_stars,
)
from src.config import Settings, get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


MAX_PER_RUN = 50
SEND_DELAY_S = 2.0
MIN_ALERT_DISCOUNT_PCT = 4
MIN_PEER_ALERT_DISCOUNT_PCT = 25
ALERT_FRESHNESS_HOURS = 6


_MATCH_SQL = text(
    f"""
    -- For each (filter, deal) pair where the deal matches the filter,
    -- emit one unsent row. The DISTINCT ON keeps it to one alert per
    -- filter per tick — we pick the BEST DISCOUNT (not the newest) so
    -- a quiet hour doesn't bury a 35% steal under a 16% routine drop.
    -- Idempotency lives in telegram_filter_notifications, not in the
    -- scalar last_notified_deal_id high-water marker, because best-first
    -- ordering and scalar cursors skip lower-id valid deals.
    SELECT DISTINCT ON (f.id)
        f.id           AS filter_id,
        f.chat_id      AS chat_id,
        f.country_iso2 AS country_iso2,
        d.id           AS deal_id,
        d.hotel_id,
        d.check_in,
        d.nights,
        d.meal_plan,
        d.discount_pct,
        d.price_uah,
        d.baseline_p50,
        d.deep_link,
        d.detection_method,
        h.name_uk      AS hotel_name_uk,
        h.canonical_slug AS hotel_slug,
        h.stars        AS hotel_stars,
        dest.name_uk   AS destination_name,
        country.name_uk AS country_name
    FROM telegram_subscriber_filters f
    JOIN telegram_subscribers s ON s.chat_id = f.chat_id AND NOT s.is_blocked
    JOIN deals d
      ON d.detected_at >= NOW() - make_interval(hours => :freshness_hours)
    JOIN hotels h ON h.id = d.hotel_id
    LEFT JOIN destinations dest ON dest.id = h.destination_id
    LEFT JOIN destinations country ON country.id = dest.parent_id
    WHERE f.is_active
      AND dest.country_iso2 = f.country_iso2
      AND (f.max_price_uah IS NULL OR d.price_uah <= f.max_price_uah)
      AND (f.min_stars      IS NULL OR h.stars     >= f.min_stars)
      AND {meal_plan_match_sql()}
      AND d.source IN ('farvater_scrape', 'live_refresh', 'ittour')
      -- Peer comparisons are useful but weaker than same-hotel history or
      -- operator promos, so keep the personal-alert floor higher. This
      -- matches the scheduler README and prevents low-signal cold-start
      -- comparisons from feeling like real hotel-specific discounts.
      AND (
        (d.detection_method = 'peer_anomaly' AND d.discount_pct >= :min_peer_discount_pct)
        OR (d.detection_method != 'peer_anomaly' AND d.discount_pct >= :min_discount_pct)
      )
      AND NOT EXISTS (
          SELECT 1
          FROM telegram_filter_notifications n
          WHERE n.filter_id = f.id
            AND n.deal_id = d.id
      )
    -- Tie-break by d.id DESC so equal discounts prefer the newest matching
    -- deal, while the notification ledger prevents repeats and skips.
    ORDER BY f.id, d.discount_pct DESC, d.id DESC
    LIMIT :max_per_run
    """
)


_MARK_NOTIFIED = text(
    """
    WITH notified AS (
        INSERT INTO telegram_filter_notifications (filter_id, deal_id)
        VALUES (:filter_id, :deal_id)
        ON CONFLICT DO NOTHING
        RETURNING deal_id
    )
    UPDATE telegram_subscriber_filters
       SET last_notified_deal_id = GREATEST(
           COALESCE(last_notified_deal_id, 0),
           :deal_id
       )
     WHERE id = :filter_id
    """
)
_NOTIFY_SUBSCRIBERS_LOCK_KEY = 2026052802
_TRY_NOTIFY_SUBSCRIBERS_LOCK = text("SELECT pg_try_advisory_lock(:lock_key)")
_RELEASE_NOTIFY_SUBSCRIBERS_LOCK = text("SELECT pg_advisory_unlock(:lock_key)")


def _render(row: Any, public_site_url: str) -> str:
    name = escape_markdown_v2(row.hotel_name_uk or "Готель")
    stars = format_stars(row.hotel_stars)
    raw_dest = row.destination_name or ""
    raw_country = getattr(row, "country_name", None) or ""
    raw_location = (
        f"{raw_dest}, {raw_country}" if raw_dest and raw_country else raw_dest or raw_country or ""
    )
    location = escape_markdown_v2(raw_location) if raw_location else ""
    nights = int(row.nights or 7)
    meal = escape_markdown_v2(format_meal_plan(row.meal_plan))
    check_in = escape_markdown_v2(format_date_short(row.check_in))
    signal = get_deal_signal_copy(getattr(row, "detection_method", None))
    semantics = render_deal_price_semantics(
        detection_method=getattr(row, "detection_method", None),
        discount_pct=row.discount_pct,
        price_uah=row.price_uah,
        baseline_uah=row.baseline_p50,
    )
    why_line = f"\n_{escape_markdown_v2(semantics.why_line)}_" if semantics.why_line else ""
    if signal.peer_comparison or signal.neutral_comparison:
        title = "🔔 *Варіант за вашою підпискою*"
    elif signal.date_anomaly:
        title = "🔔 *Цікава дата за вашою підпискою*"
    else:
        title = "🔔 *Знижка за вашою підпискою*"

    return (
        f"{title}\n\n" f"🏨 *{name}* {stars}".rstrip()
        + "\n"
        + (f"📍 {location}\n" if location else "")
        + f"📅 {check_in} · {escape_markdown_v2(format_nights(nights))} · {meal}\n\n"
        + f"{semantics.price_line}\n"
        + semantics.headline
        + why_line
    )


async def notify_subscribers() -> int:
    """Returns the number of personal alerts sent this tick."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.info("notify_subscribers.skipped", reason="no_token")
        return 0

    async with async_session_factory() as lock_db:
        acquired = (
            await lock_db.execute(
                _TRY_NOTIFY_SUBSCRIBERS_LOCK,
                {"lock_key": _NOTIFY_SUBSCRIBERS_LOCK_KEY},
            )
        ).scalar_one()
        if not acquired:
            log.info("notify_subscribers.skipped", reason="already_running")
            return 0
        try:
            return await _notify_subscribers_locked(settings)
        finally:
            await lock_db.execute(
                _RELEASE_NOTIFY_SUBSCRIBERS_LOCK,
                {"lock_key": _NOTIFY_SUBSCRIBERS_LOCK_KEY},
            )


async def _notify_subscribers_locked(settings: Settings) -> int:
    """Returns the number of personal alerts sent this tick."""

    started_at = datetime.now(UTC)
    assert settings.telegram_bot_token is not None
    bot = make_bot(settings.telegram_bot_token)
    sent = 0
    failed = 0

    try:
        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    _MATCH_SQL,
                    {
                        "max_per_run": MAX_PER_RUN,
                        "min_discount_pct": MIN_ALERT_DISCOUNT_PCT,
                        "min_peer_discount_pct": MIN_PEER_ALERT_DISCOUNT_PCT,
                        "freshness_hours": ALERT_FRESHNESS_HOURS,
                    },
                )
            ).all()

        if not rows:
            log.info("notify_subscribers.empty")
            return 0

        # Site URL for the deep-link button; aiogram InlineKeyboardMarkup
        # imports stay inside the function to keep the module import-light.
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        for row in rows:
            text_body = _render(row, settings.public_site_url)
            kb_rows: list[list[InlineKeyboardButton]] = []

            primary_url = row.deep_link
            if not primary_url:
                primary_url = public_hotel_url(
                    settings.public_site_url,
                    row.hotel_slug,
                    medium="alert",
                )
            if primary_url:
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text="📖 Готель",
                            url=primary_url,
                        )
                    ]
                )
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text="❌ Видалити цю підписку",
                        callback_data=f"sub:del:{row.filter_id}",
                    )
                ]
            )
            kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

            try:
                await bot.send_message(
                    chat_id=row.chat_id,
                    text=text_body,
                    parse_mode="MarkdownV2",
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                sent += 1
                # Mark this filter/deal pair as notified so we don't resend
                # it on the next tick. The scalar cursor remains a high-water
                # marker for legacy/admin visibility only.
                async with async_session_factory() as db:
                    await db.execute(
                        _MARK_NOTIFIED,
                        {"deal_id": row.deal_id, "filter_id": row.filter_id},
                    )
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning(
                    "notify_subscribers.send_failed",
                    chat_id=row.chat_id,
                    filter_id=row.filter_id,
                    error=str(exc),
                )
            await asyncio.sleep(SEND_DELAY_S)

    finally:
        await bot.session.close()

    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    log.info(
        "notify_subscribers.completed",
        sent=sent,
        failed=failed,
        elapsed_s=round(elapsed, 2),
    )
    if rows and sent == 0 and failed == len(rows):
        raise RuntimeError(f"all Telegram subscriber alerts failed for {len(rows)} matches")
    return sent
