"""Publish unposted deals to the Telegram channel.

Runs every 15 minutes. Skips gracefully when ``TELEGRAM_BOT_TOKEN`` is
empty (typical in dev) — the rest of the scheduler keeps running.

Daily cap is enforced *mid-run aware*: if we're 28/30 for today, we only
take 2 deals from this tick. This avoids the foot-gun of "all 5 unposted
deals in this tick get posted, even though 28 + 5 > 30".

Per-hotel cooldown is already enforced upstream by ``detect_deals``, but
we re-check at SELECT time to defend against the race where a previous
detect tick inserted N deals for the same hotel from different operators
in the same minute.

Telegram throttling: aiogram has middleware for this, but for MVP we just
sleep ``telegram_send_delay_seconds`` between sends. 2s × 5 deals = 10s
worst case; well under the 30 msg/sec channel-broadcast soft limit.
"""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import text

from src.config import get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.publishers.broadcast import broadcast_deal, escape_markdown_v2, make_bot

log = get_logger(__name__)

# Pre-escaped MarkdownV2 template. Literal punctuation that MarkdownV2
# reserves (`-`, `(`, `)`, `|`, `.`, `!`) is already `\`-escaped here.
# DB substitutions are escape_markdown_v2()'d at render time.
#
# Substitution placeholders use {…} so .format() handles them — they
# don't conflict with the (escaped) curly braces of the surrounding
# Telegram syntax (we have none).
_DEAL_TEMPLATE = (
    "🔥 *ГАРЯЧА ЗНИЖКА \\-{discount_pct}%*\n"
    "\n"
    "🏨 *{hotel_name}* {stars_str}\n"
    "📍 {destination}\n"
    "📅 {check_in_formatted} \\({nights} ноч\\) \\| {meal_plan} \\| 2 дорослих\n"
    "\n"
    "💰 *{price_formatted}* \\(зазвичай {baseline_formatted}\\)\n"
    "🛒 [Купити на {operator_display_name} →]({deep_link})"
)


# Pull all the fields a post needs in one query. Operator + destination
# names live behind FKs; doing the join in SQL keeps round-trips down.
#
# We join destinations TWICE — once for the region (where the hotel lives)
# and once via `parent_id` for the country. After multi-country expansion
# "Хургада" alone is ambiguous (could be Egypt or Tunisia for a future
# reader), so the broadcast template renders "Хургада, Єгипет".
_SELECT_UNPOSTED = text(
    """
    SELECT
        d.id,
        d.hotel_id,
        d.discount_pct,
        d.price_uah,
        d.baseline_p50,
        d.check_in,
        d.nights,
        d.meal_plan,
        d.deep_link,
        h.name_uk        AS hotel_name,
        h.stars          AS stars,
        region.name_uk   AS region_name,
        country.name_uk  AS country_name,
        o.display_name   AS operator_display_name
    FROM deals d
    JOIN hotels h               ON h.id = d.hotel_id
    LEFT JOIN destinations region  ON region.id = h.destination_id
    LEFT JOIN destinations country ON country.id = region.parent_id
    JOIN operators o            ON o.id = d.operator_id
    WHERE d.posted_at IS NULL
      -- migration 004 added `source`. NULL = synthetic seed (demo data)
      -- and must NEVER be broadcast — those would mis-advertise prices
      -- that don't exist. Real ingest paths set source explicitly:
      --   'farvater_scrape'  — twice-daily snapshot
      --   'live_refresh'     — on-demand /api/hotels/{id}/refresh
      --   'ittour'           — direct partner API (future)
      AND d.source IS NOT NULL
      AND d.source IN ('farvater_scrape', 'live_refresh', 'ittour')
    ORDER BY d.detected_at DESC
    LIMIT :lim
    """
)

_COUNT_TODAY = text(
    """
    SELECT COUNT(*) AS n
    FROM deals
    WHERE posted_at::date = :today
    """
)

_MARK_POSTED = text(
    """
    UPDATE deals
    SET posted_at = NOW(),
        telegram_msg_id = :msg_id
    WHERE id = :deal_id
    """
)


_MONTHS_UK = (
    "",  # 1-indexed
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)


def _format_check_in(d: date) -> str:
    """`2026-06-12` -> `12 червня`."""
    return f"{d.day} {_MONTHS_UK[d.month]}"


def _format_uah(amount: int) -> str:
    """Thousand-separated with a non-breaking-ish space + ₴."""
    return f"{amount:,}".replace(",", " ") + " ₴"


def _stars_str(stars: int | None) -> str:
    if not stars:
        return ""
    return "⭐" * int(stars)


def _format_location(region: str | None, country: str | None) -> str:
    """`region` + `country` → 'Region, Country' / 'Country' / '—'.

    Region-only case shouldn't happen post-multi-country migration but we
    keep the fallback so a misconfigured destination doesn't crash the post.
    """
    if region and country:
        return f"{region}, {country}"
    return region or country or "—"


def _render_deal(row: object) -> str:
    """Render a deal row to a MarkdownV2 message. Pure / testable."""
    # All DB strings get escaped at the boundary. Numbers are safe.
    return _DEAL_TEMPLATE.format(
        discount_pct=escape_markdown_v2(f"{float(row.discount_pct):.0f}"),
        hotel_name=escape_markdown_v2(row.hotel_name),
        stars_str=_stars_str(row.stars),
        destination=escape_markdown_v2(
            _format_location(
                getattr(row, "region_name", None),
                getattr(row, "country_name", None),
            )
        ),
        check_in_formatted=escape_markdown_v2(_format_check_in(row.check_in)),
        nights=row.nights,
        meal_plan=escape_markdown_v2(row.meal_plan),
        price_formatted=escape_markdown_v2(_format_uah(row.price_uah)),
        baseline_formatted=escape_markdown_v2(_format_uah(row.baseline_p50)),
        operator_display_name=escape_markdown_v2(row.operator_display_name),
        # deep_link goes inside Markdown link parens — `(...)` already
        # escaped in template, but `)` literally in URL would break out.
        # MarkdownV2 link-url escaping is `\)` and `\\`.
        deep_link=(row.deep_link or "https://fasttravel.com.ua")
        .replace("\\", "\\\\")
        .replace(")", "\\)"),
    )


async def post_deals() -> None:
    settings = get_settings()

    if not settings.telegram_enabled:
        log.warning(
            "post_deals.skipped",
            reason="no_token",
            note="set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID to enable",
        )
        return

    today = date.today()

    async with async_session_factory() as db:
        posted_today = (await db.execute(_COUNT_TODAY, {"today": today})).scalar_one()
        remaining = max(0, settings.deals_daily_cap - int(posted_today))
        if remaining == 0:
            log.info(
                "post_deals.skipped",
                reason="daily_cap_reached",
                posted_today=int(posted_today),
                cap=settings.deals_daily_cap,
            )
            return

        # Take the smaller of: this-tick allowance, daily-cap remainder.
        limit = min(settings.deals_per_post_tick, remaining)
        rows = (await db.execute(_SELECT_UNPOSTED, {"lim": limit})).all()

    if not rows:
        log.info("post_deals.no_unposted_deals")
        return

    bot = make_bot(settings.telegram_bot_token or "")
    channel: str | int = settings.telegram_channel_id or ""
    # Channel ids of the `-100...` form are integers on the wire; aiogram
    # accepts either, but we coerce so 429-retry diagnostics show the
    # canonical type.
    if isinstance(channel, str) and channel.lstrip("-").isdigit():
        channel = int(channel)

    sent = 0
    try:
        for i, row in enumerate(rows):
            try:
                msg_text = _render_deal(row)
                msg_id = await broadcast_deal(bot, channel, msg_text)
            except Exception as exc:
                log.error(
                    "post_deals.send_failed",
                    deal_id=row.id,
                    hotel_id=row.hotel_id,
                    error=str(exc),
                )
                # Don't mark this deal posted — next tick will retry.
                continue

            async with async_session_factory() as db:
                await db.execute(
                    _MARK_POSTED,
                    {"msg_id": int(msg_id), "deal_id": int(row.id)},
                )
                await db.commit()
            sent += 1
            log.info(
                "post_deals.sent",
                deal_id=row.id,
                hotel_id=row.hotel_id,
                discount_pct=float(row.discount_pct),
                msg_id=int(msg_id),
            )

            # Sleep between posts (skip after the last to avoid wasted wait).
            if i < len(rows) - 1:
                await asyncio.sleep(settings.telegram_send_delay_seconds)
    finally:
        # aiogram Bot owns an httpx session — must be closed or the
        # event loop emits "unclosed connection" warnings on shutdown.
        await bot.session.close()

    log.info("post_deals.completed", sent=sent, considered=len(rows))
