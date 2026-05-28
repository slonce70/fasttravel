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
from typing import Protocol

from sqlalchemy import text

from shared.deal_rendering import render_deal_hotel_context, render_deal_price_semantics
from shared.publishers.broadcast import (
    broadcast_deal,
    escape_markdown_v2,
    escape_markdown_v2_url,
    make_bot,
)
from shared.site_urls import public_hotel_url
from shared.text_uk import (
    format_date_full,
    format_location,
    format_meal_plan,
    format_nights,
    format_stars,
)
from src.config import Settings, get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)
MIN_BROADCAST_DISCOUNT_PCT = 4


class _DealRow(Protocol):
    discount_pct: float
    hotel_name: str
    hotel_slug: str | None
    stars: int | None
    region_name: str | None
    country_name: str | None
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    baseline_p50: int
    operator_display_name: str
    deep_link: str | None
    detection_method: str | None
    description_uk: str | None
    review_score: float | None
    review_count: int | None


# Pre-escaped MarkdownV2 template. Literal punctuation that MarkdownV2
# reserves (`-`, `(`, `)`, `|`, `.`, `!`) is already `\`-escaped here.
# DB substitutions are escape_markdown_v2()'d at render time.
#
# Substitution placeholders use {…} so .format() handles them — they
# don't conflict with the (escaped) curly braces of the surrounding
# Telegram syntax (we have none).
#
# {headline} and {price_line} are pre-assembled per detection_method
# because date-anomaly and percentile/promo deals carry different price
# semantics: date-anomaly's baseline is a trimmed neighbouring-date baseline,
# not a price the user would otherwise pay for THIS booking, so we
# render it without a "saved X ₴" framing.
_DEAL_TEMPLATE = (
    "{headline}\n"
    "\n"
    "🏨 *{hotel_name}* {stars_str}\n"
    "📍 {destination}\n"
    "{hotel_context}"
    "📅 {check_in_formatted} · {nights_label} · {meal_plan_label}\n"
    "\n"
    "{price_line}\n"
    "{why_line}"
    "🛒 [Забронювати на {operator_display_name} →]({deep_link})"
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
        d.detection_method,
        h.name_uk        AS hotel_name,
        h.canonical_slug AS hotel_slug,
        h.stars          AS stars,
        h.description_uk AS description_uk,
        h.review_score   AS review_score,
        h.review_count   AS review_count,
        region.name_uk   AS region_name,
        country.name_uk  AS country_name,
        o.display_name   AS operator_display_name
    FROM deals d
    JOIN hotels h               ON h.id = d.hotel_id
    LEFT JOIN destinations region  ON region.id = h.destination_id
    LEFT JOIN destinations country ON country.id = region.parent_id
    JOIN operators o            ON o.id = d.operator_id
    WHERE d.posted_at IS NULL
      AND d.discount_pct >= :min_discount_pct
      AND d.detection_method NOT LIKE 'bucket_%'
      -- Do not drain old unposted backlog into the public channel. A deal
      -- is a live price signal; if the bot/channel was down for hours, the
      -- detector will find fresh candidates on the next tick.
      AND d.detected_at >= NOW() - INTERVAL '6 hours'
      -- Channel-only filter: peer_anomaly (cold-start) compares the
      -- price to OTHER hotels in the same destination+stars bucket, not
      -- to this hotel's own history. That's a useful UI signal in the
      -- /api/deals feed (where users can see the method), but in the
      -- channel post the phrasing "знижка" implies "vs this hotel's
      -- normal price" — which peer-comparison doesn't actually prove.
      -- Keep cold-start in the UI feed and personal alerts (with a
      -- higher discount floor), but not in the public channel.
      AND d.detection_method != 'peer_anomaly'
      -- migration 004 added `source`. Legacy/imported rows without source
      -- must NEVER be broadcast because they cannot prove a live price
      -- origin. Real ingest paths set source explicitly:
      --   'farvater_scrape'  — twice-daily snapshot
      --   'live_refresh'     — on-demand /api/hotels/{id}/refresh
      --   'ittour'           — direct partner API (future)
      AND d.source IS NOT NULL
      AND d.source IN ('farvater_scrape', 'live_refresh', 'ittour')
      -- Rows claimed for an in-flight Telegram send use a negative sentinel.
      -- The claim has a TTL: a process crash between claim and send/mark must
      -- not hide the deal forever, but immediate retries are still suppressed.
      AND (
          d.telegram_msg_id IS NULL
          OR (
              d.telegram_msg_id = :pending_msg_id
              AND d.telegram_claimed_at
                  < NOW() - make_interval(mins => CAST(:claim_ttl_minutes AS INTEGER))
          )
      )
    -- Channel content rule: the biggest savings always lead, with the
    -- newest detection as the tie-break. Pre-audit this was
    -- `ORDER BY detected_at DESC` — fresh first — but that buried
    -- 40% promos under 15% ones whenever a tick caught both. The
    -- product is "we find the steals", so the steal goes first.
    ORDER BY d.discount_pct DESC, d.detected_at DESC
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
        telegram_msg_id = :msg_id,
        telegram_claimed_at = NULL
    WHERE id = :deal_id
      AND posted_at IS NULL
    """
)
_PENDING_TELEGRAM_MSG_ID = -1
_CLAIM_FOR_POSTING = text(
    """
    UPDATE deals
    SET telegram_msg_id = :pending_msg_id,
        telegram_claimed_at = NOW()
    WHERE id = :deal_id
      AND posted_at IS NULL
      AND (
          telegram_msg_id IS NULL
          OR (
              telegram_msg_id = :pending_msg_id
              AND telegram_claimed_at
                  < NOW() - make_interval(mins => CAST(:claim_ttl_minutes AS INTEGER))
          )
      )
    RETURNING id
    """
)
_RELEASE_POSTING_CLAIM = text(
    """
    UPDATE deals
    SET telegram_msg_id = NULL,
        telegram_claimed_at = NULL
    WHERE id = :deal_id
      AND posted_at IS NULL
      AND telegram_msg_id = :pending_msg_id
    """
)
_POST_DEALS_LOCK_KEY = 2026052801
_POSTING_CLAIM_TTL_MINUTES = 30
_TRY_POST_DEALS_LOCK = text("SELECT pg_try_advisory_lock(:lock_key)")
_RELEASE_POST_DEALS_LOCK = text("SELECT pg_advisory_unlock(:lock_key)")


def _format_hotel_context(row: _DealRow) -> str:
    return render_deal_hotel_context(
        review_score=getattr(row, "review_score", None),
        review_count=getattr(row, "review_count", None),
        description_uk=getattr(row, "description_uk", None),
    )


def _deal_link(row: _DealRow, public_site_url: str) -> str:
    if row.deep_link:
        return row.deep_link

    hotel_slug = getattr(row, "hotel_slug", None)
    return public_hotel_url(public_site_url, hotel_slug, source="") or public_site_url


def _render_deal(row: _DealRow, *, public_site_url: str) -> str:
    """Render a deal row to a MarkdownV2 message. Pure / testable."""
    meal_label = format_meal_plan(row.meal_plan)
    semantics = render_deal_price_semantics(
        detection_method=getattr(row, "detection_method", None),
        discount_pct=row.discount_pct,
        price_uah=row.price_uah,
        baseline_uah=row.baseline_p50,
    )
    why_line = f"_{escape_markdown_v2(semantics.why_line)}_\n\n" if semantics.why_line else ""

    return _DEAL_TEMPLATE.format(
        headline=semantics.headline,
        price_line=semantics.price_line,
        hotel_name=escape_markdown_v2(row.hotel_name),
        stars_str=format_stars(row.stars),
        destination=escape_markdown_v2(
            format_location(
                getattr(row, "region_name", None),
                getattr(row, "country_name", None),
            )
        ),
        hotel_context=_format_hotel_context(row),
        check_in_formatted=escape_markdown_v2(format_date_full(row.check_in)),
        nights_label=escape_markdown_v2(format_nights(int(row.nights))),
        meal_plan_label=escape_markdown_v2(meal_label),
        why_line=why_line,
        operator_display_name=escape_markdown_v2(row.operator_display_name),
        deep_link=escape_markdown_v2_url(_deal_link(row, public_site_url)),
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

    async with async_session_factory() as lock_db:
        acquired = (
            await lock_db.execute(_TRY_POST_DEALS_LOCK, {"lock_key": _POST_DEALS_LOCK_KEY})
        ).scalar_one()
        if not acquired:
            log.info("post_deals.skipped", reason="already_running")
            return
        try:
            await _post_deals_locked(settings)
        finally:
            await lock_db.execute(
                _RELEASE_POST_DEALS_LOCK,
                {"lock_key": _POST_DEALS_LOCK_KEY},
            )


async def _post_deals_locked(settings: Settings) -> None:
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
        rows = (
            await db.execute(
                _SELECT_UNPOSTED,
                {
                    "lim": limit,
                    "min_discount_pct": MIN_BROADCAST_DISCOUNT_PCT,
                    "pending_msg_id": _PENDING_TELEGRAM_MSG_ID,
                    "claim_ttl_minutes": _POSTING_CLAIM_TTL_MINUTES,
                },
            )
        ).all()

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
    failed = 0
    try:
        for i, row in enumerate(rows):
            async with async_session_factory() as db:
                claimed = (
                    await db.execute(
                        _CLAIM_FOR_POSTING,
                        {
                            "pending_msg_id": _PENDING_TELEGRAM_MSG_ID,
                            "claim_ttl_minutes": _POSTING_CLAIM_TTL_MINUTES,
                            "deal_id": int(row.id),
                        },
                    )
                ).scalar_one_or_none()
                await db.commit()
            if claimed is None:
                log.info("post_deals.claim_skipped", deal_id=row.id, reason="already_claimed")
                continue

            try:
                msg_text = _render_deal(row, public_site_url=settings.public_site_url)
                msg_id = await broadcast_deal(bot, channel, msg_text)
            except Exception as exc:
                failed += 1
                async with async_session_factory() as db:
                    await db.execute(
                        _RELEASE_POSTING_CLAIM,
                        {
                            "pending_msg_id": _PENDING_TELEGRAM_MSG_ID,
                            "deal_id": int(row.id),
                        },
                    )
                    await db.commit()
                log.error(
                    "post_deals.send_failed",
                    deal_id=row.id,
                    hotel_id=row.hotel_id,
                    error=str(exc),
                )
                # Don't mark this deal posted — next tick will retry.
                continue

            async with async_session_factory() as db:
                mark_result = await db.execute(
                    _MARK_POSTED,
                    {
                        "msg_id": int(msg_id),
                        "pending_msg_id": _PENDING_TELEGRAM_MSG_ID,
                        "deal_id": int(row.id),
                    },
                )
                await db.commit()
            if getattr(mark_result, "rowcount", 1) != 1:
                raise RuntimeError(f"Telegram send could not be recorded for deal {int(row.id)}")
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

    if rows and sent == 0 and failed == len(rows):
        log.error("post_deals.failed", sent=sent, failed=failed, considered=len(rows))
        raise RuntimeError(f"all Telegram sends failed for {len(rows)} deals")
    log.info("post_deals.completed", sent=sent, failed=failed, considered=len(rows))
