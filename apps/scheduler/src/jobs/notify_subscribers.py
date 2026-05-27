"""notify_subscribers — one-to-one Telegram pings for matching deals.

Runs after `detect_deals` on every hourly tick. For each subscriber
filter, finds deals that:
  - have detected_at >= last_notified_deal_id (or NULL for first run)
  - match country, max_price, min_stars
and sends one DM per deal. After each successful send we bump
`last_notified_deal_id` so a re-run within the same hour is idempotent.

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

from shared.publishers.broadcast import escape_markdown_v2, make_bot
from src.config import get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


MAX_PER_RUN = 50
SEND_DELAY_S = 2.0


_MATCH_SQL = text(
    """
    -- For each (filter, deal) pair where the deal matches the filter
    -- AND was detected after the last notification we sent on that
    -- filter, emit one row. The DISTINCT ON keeps it to one alert per
    -- filter per tick — we pick the BEST DISCOUNT (not the newest) so
    -- a quiet hour doesn't bury a 35% steal under a 16% routine drop.
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
        dest.name_uk   AS destination_name
    FROM telegram_subscriber_filters f
    JOIN telegram_subscribers s ON s.chat_id = f.chat_id AND NOT s.is_blocked
    JOIN deals d
      ON d.detected_at >= NOW() - INTERVAL '24 hours'
      AND (f.last_notified_deal_id IS NULL OR d.id > f.last_notified_deal_id)
    JOIN hotels h ON h.id = d.hotel_id
    LEFT JOIN destinations dest ON dest.id = h.destination_id
    WHERE f.is_active
      AND dest.country_iso2 = f.country_iso2
      AND (f.max_price_uah IS NULL OR d.price_uah <= f.max_price_uah)
      AND (f.min_stars      IS NULL OR h.stars     >= f.min_stars)
      AND d.source IN ('farvater_scrape', 'live_refresh', 'ittour')
      -- Higher floor for peer_anomaly (cold-start): peer-group comparison
      -- has more false positives than a hotel's own-history percentile or
      -- a calendar date-dip, so we only DM the subscriber on big drops.
      -- Other methods keep their natural threshold (>0% measurable).
      AND (
          d.detection_method != 'peer_anomaly'
          OR d.discount_pct >= 25
      )
    -- Tie-break by d.id DESC so the cursor `f.last_notified_deal_id`
    -- advances monotonically even when two deals tie on discount.
    ORDER BY f.id, d.discount_pct DESC, d.id DESC
    LIMIT :max_per_run
    """
)


_MARK_NOTIFIED = text(
    """
    UPDATE telegram_subscriber_filters
       SET last_notified_deal_id = :deal_id
     WHERE id = :filter_id
    """
)


def _format_uah(price: int | None) -> str:
    if price is None:
        return "—"
    return f"{int(price):,}".replace(",", " ") + " ₴"


def _stars_str(stars: int | None) -> str:
    if not stars:
        return ""
    return "⭐" * int(stars)


_MEAL_LABELS = {
    "AI": "Все включено",
    "UAI": "Ультра все включено",
    "HB": "Напівпансіон",
    "BB": "Сніданок",
    "FB": "Повний пансіон",
    "RO": "Без харчування",
}

# Mirrors post_deals._WHY_LINES so the personal alert tells the
# subscriber WHY this deal beat the others — calendar dip vs operator
# promo vs hotel-history percentile vs peer-group cold-start.
_WHY_LINES = {
    "calendar_anomaly": "📉 Аномально дешева дата у цьому готелі",
    "promo_discount": "🏷 Спецціна оператора",
    "percentile": "📊 Нижче історичної ціни цього готелю",
    "peer_anomaly": "📊 Дешевше за середнє по сусідніх готелях",
}


def _render(row: Any, public_site_url: str) -> str:
    discount = int(round(float(row.discount_pct or 0)))
    name = escape_markdown_v2(row.hotel_name_uk or "Готель")
    stars = _stars_str(row.hotel_stars)
    dest = escape_markdown_v2(row.destination_name or "")
    nights = int(row.nights or 7)
    raw_meal = row.meal_plan or ""
    meal = escape_markdown_v2(_MEAL_LABELS.get(raw_meal, raw_meal))
    price = escape_markdown_v2(_format_uah(row.price_uah))
    baseline_int = int(row.baseline_p50 or 0)
    savings = max(0, baseline_int - int(row.price_uah or 0))
    savings_fmt = escape_markdown_v2(_format_uah(savings))
    baseline = escape_markdown_v2(_format_uah(baseline_int))
    check_in = escape_markdown_v2(str(row.check_in))
    method = (getattr(row, "detection_method", None) or "").lower()
    why = _WHY_LINES.get(method, "")
    why_line = f"\n_{escape_markdown_v2(why)}_" if why else ""

    return (
        f"🔔 *Знижка за вашою підпискою*\n"
        f"🌍 {escape_markdown_v2(row.country_iso2)}\n\n"
        f"🏨 *{name}* {stars}".rstrip()
        + "\n"
        + (f"📍 {dest}\n" if dest else "")
        + f"📅 {check_in} · {nights} ноч\\. · {meal}\n\n"
        + f"💰 *{price}* ~{baseline}~\n"
        + f"🔥 *\\-{discount}%* · економія *{savings_fmt}*"
        + why_line
    )


async def notify_subscribers() -> int:
    """Returns the number of personal alerts sent this tick."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.info("notify_subscribers.skipped", reason="no_token")
        return 0

    started_at = datetime.now(UTC)
    bot = make_bot(settings.telegram_bot_token)
    sent = 0

    try:
        async with async_session_factory() as db:
            rows = (await db.execute(_MATCH_SQL, {"max_per_run": MAX_PER_RUN})).all()

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
            if not primary_url and row.hotel_slug and settings.public_site_url:
                primary_url = (
                    f"{settings.public_site_url.rstrip('/')}/hotels/{row.hotel_slug}"
                    "?utm_source=tg_bot&utm_medium=alert"
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
                        text="🔕 Призупинити підписку",
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
                # Mark this filter as notified for this deal so we don't
                # re-send it on the next tick.
                async with async_session_factory() as db:
                    await db.execute(
                        _MARK_NOTIFIED,
                        {"deal_id": row.deal_id, "filter_id": row.filter_id},
                    )
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
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
        elapsed_s=round(elapsed, 2),
    )
    return sent
