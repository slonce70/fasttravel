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

from shared.deal_signals import get_deal_signal_copy
from shared.publishers.broadcast import broadcast_deal, escape_markdown_v2, make_bot
from shared.text_uk import format_nights, format_reviews
from src.config import get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)
MIN_BROADCAST_DISCOUNT_PCT = 15


class _DealRow(Protocol):
    discount_pct: float
    hotel_name: str
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
_DEAL_TEMPLATE = (
    "🔥 *\\-{discount_pct}% · економія {savings_formatted}*\n"
    "\n"
    "🏨 *{hotel_name}* {stars_str}\n"
    "📍 {destination}\n"
    "{hotel_context}"
    "📅 {check_in_formatted} · {nights_label} · {meal_plan_label}\n"
    "\n"
    "💰 *{price_formatted}* {strikethrough}\n"
    "{why_line}"
    "🛒 [Забронювати на {operator_display_name} →]({deep_link})"
)


# Short, customer-friendly meal plan names. RO/BB/AI codes are operator
# jargon — the channel reader cares about whether breakfast is included.
_MEAL_LABELS = {
    "AI": "Все включено",
    "UAI": "Ультра все включено",
    "HB": "Напівпансіон",
    "BB": "Сніданок",
    "FB": "Повний пансіон",
    "RO": "Без харчування",
}


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
        telegram_msg_id = :msg_id
    WHERE id = :deal_id
    """
)


_MONTHS_UK = (
    "",  # 1-indexed
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)


def _format_check_in(d: date) -> str:
    """`2026-06-12` -> `12 червня`."""
    return f"{d.day} {_MONTHS_UK[d.month]}"


def _format_uah(amount: int) -> str:
    """Thousand-separated with a non-breaking-ish space + ₴."""
    return f"{amount:,}".replace(",", " ") + " ₴"


def _format_hotel_context(row: _DealRow) -> str:
    lines: list[str] = []
    review_score = getattr(row, "review_score", None)
    review_count = int(getattr(row, "review_count", 0) or 0)
    if review_score is not None and review_count > 0:
        score = f"{float(review_score):.1f}/10"
        lines.append(f"⭐ {score} · {format_reviews(review_count)}")

    description = " ".join((getattr(row, "description_uk", None) or "").split())
    if description:
        if len(description) > 140:
            description = description[:137].rstrip() + "..."
        lines.append(f"ℹ️ {description}")

    if not lines:
        return ""
    return "".join(f"{escape_markdown_v2(line)}\n" for line in lines)


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


def _render_deal(row: _DealRow) -> str:
    """Render a deal row to a MarkdownV2 message. Pure / testable."""
    # Savings in absolute UAH — the percentage alone doesn't communicate
    # impact when peer prices vary wildly across categories. baseline_p50
    # is always >= price_uah by construction (only positive-discount
    # rows reach this template).
    savings = max(0, int(row.baseline_p50) - int(row.price_uah))
    raw_meal = row.meal_plan or ""
    meal_label = _MEAL_LABELS.get(raw_meal, raw_meal)

    # Inline strike-through of the typical price. MarkdownV2 syntax is
    # `~text~`. Escaped braces in the template would interfere with
    # .format(), so we render the strikethrough block here.
    strikethrough = (
        f"~{escape_markdown_v2(_format_uah(int(row.baseline_p50)))}~" if savings > 0 else ""
    )

    why = get_deal_signal_copy(getattr(row, "detection_method", None)).why_line
    why_line = f"_{escape_markdown_v2(why)}_\n\n" if why else ""

    # All DB strings get escaped at the boundary. Numbers are safe.
    return _DEAL_TEMPLATE.format(
        discount_pct=escape_markdown_v2(f"{float(row.discount_pct):.0f}"),
        savings_formatted=escape_markdown_v2(_format_uah(savings)),
        hotel_name=escape_markdown_v2(row.hotel_name),
        stars_str=_stars_str(row.stars),
        destination=escape_markdown_v2(
            _format_location(
                getattr(row, "region_name", None),
                getattr(row, "country_name", None),
            )
        ),
        hotel_context=_format_hotel_context(row),
        check_in_formatted=escape_markdown_v2(_format_check_in(row.check_in)),
        nights_label=escape_markdown_v2(format_nights(int(row.nights))),
        meal_plan_label=escape_markdown_v2(meal_label),
        price_formatted=escape_markdown_v2(_format_uah(row.price_uah)),
        strikethrough=strikethrough,
        why_line=why_line,
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
        rows = (
            await db.execute(
                _SELECT_UNPOSTED,
                {"lim": limit, "min_discount_pct": MIN_BROADCAST_DISCOUNT_PCT},
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
