"""Post the daily "Найдешевші тури" digest to the Telegram channel.

This is the **channel surface** of the absolute-cheap "cheapest tours" feature
(see docs/superpowers/specs/2026-06-03-cheapest-tours-design.md). It is the
companion to — and deliberately distinct from — the anomaly deal-detector
(``post_deals``): it surfaces genuinely cheap upcoming tours («ціна від»), NOT
discounts. There is no «знижка», no «−X%», no strike-through, no baseline.

What it does, once per day:

  1. Runs the shared :func:`shared.cheapest_tours.cheapest_tours_sql` directly
     against the DB (the single source every surface reads — we do NOT call the
     API). TOP-``PER_COUNTRY`` distinct hotels per country, ``stars >= MIN_STARS``,
     check_in +3..+90 days, behind the 36h freshness gate.
  2. Groups the flat ranked list by country and renders ONE MarkdownV2 digest
     «💸 Найдешевші тури по напрямках».
  3. Sends it to the channel via :func:`shared.publishers.broadcast.broadcast_deal`
     with link previews disabled (a digest of many links would otherwise render
     a giant preview card).

Feature flag: ``FT_CHEAPEST_DIGEST_ENABLED`` (env). Default OFF — exactly like
``static_tours_sweep`` — so deploying the job does NOT auto-spam the channel
until the owner flips it on. When the flag is OFF the job logs and returns.

Cadence: daily at 08:00 Europe/Kyiv (registered in ``scheduler/src/main.py``).
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from itertools import groupby
from typing import Protocol

from sqlalchemy import text

from shared.cheapest_tours import MIN_STARS, PER_COUNTRY, cheapest_tours_sql
from shared.publishers.broadcast import (
    broadcast_deal,
    escape_markdown_v2,
    escape_markdown_v2_url,
    make_bot,
)
from shared.site_urls import public_hotel_url
from shared.text_uk import (
    format_date_full,
    format_meal_plan,
    format_nights,
    format_stars,
    format_uah,
)
from src.config import get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)

FEATURE_FLAG_ENV = "FT_CHEAPEST_DIGEST_ENABLED"

# Pre-escaped MarkdownV2 header. The em-dash/punctuation a digest needs is
# escaped here; DB-supplied substrings are escape_markdown_v2()'d at render.
_DIGEST_TITLE = "💸 *Найдешевші тури по напрямках*"

# Telegram caps a message at 4096 UTF-16 code units. We chunk the ONE daily
# digest on country boundaries (never splitting a country) and keep a generous
# margin: the 💸/🌍 emoji are surrogate pairs (2 UTF-16 units, but len() counts
# 1), so a conservative budget on len() guarantees we stay under the real limit.
# At TOP-3 × ~11 destinations the digest is ~6k chars — it cannot fit one
# message, so 1-2 chunks is expected; small result sets still emit ONE message.
_CHUNK_CHAR_BUDGET = 3500


class _CheapRow(Protocol):
    country_iso2: str
    country_name: str | None
    hotel_id: int
    hotel_slug: str
    hotel_name: str
    stars: int
    review_score: float | None
    review_count: int
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    deep_link: str | None
    rank: int


def _is_enabled() -> bool:
    val = os.getenv(FEATURE_FLAG_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _hotel_link(row: _CheapRow, public_site_url: str) -> str:
    """Deep link to the offer, falling back to the public hotel page."""
    deep_link = getattr(row, "deep_link", None)
    if deep_link:
        return str(deep_link)
    return public_hotel_url(public_site_url, getattr(row, "hotel_slug", None), source="") or ""


def _render_hotel_line(row: _CheapRow, *, public_site_url: str) -> str:
    """One hotel line: «ціна від» only — never a discount.

    Format (compact, to stay well under Telegram's 4096-char message limit
    even at ~11 countries × 3 hotels):

      • <a>Hotel ⭐⭐⭐</a> — ціна від 18 210 ₴ · 7 ночей · сніданки · 6 червня
    """
    name = escape_markdown_v2(row.hotel_name)
    stars = format_stars(getattr(row, "stars", None))
    name_with_stars = f"{name} {stars}".rstrip()

    link = _hotel_link(row, public_site_url)
    label = f"[{name_with_stars}]({escape_markdown_v2_url(link)})" if link else name_with_stars

    # «ціна від» is the ONLY price claim. No baseline, no «−X%», no strike-through.
    price = escape_markdown_v2(f"ціна від {format_uah(row.price_uah)}")
    nights = escape_markdown_v2(format_nights(int(row.nights)))
    meal = format_meal_plan(row.meal_plan)
    check_in = escape_markdown_v2(format_date_full(row.check_in))

    parts = [price, nights]
    if meal:
        parts.append(escape_markdown_v2(meal))
    parts.append(check_in)
    # " · " — the middle-dot is not a MarkdownV2 reserved char, no escaping.
    tail = " · ".join(parts)
    # The leading bullet "•" is literal; the en-dash "—" too (neither reserved).
    return f"• {label} — {tail}"


def render_digest(rows: list[_CheapRow], *, public_site_url: str) -> list[str]:
    """Render the daily digest into MarkdownV2 message chunks. Pure / testable.

    Groups by ``country_iso2`` — the shared SQL already orders by country_name,
    rank, hotel_id, so consecutive rows form each country block. The blocks are
    greedily packed into chunks on country boundaries (a country is never split)
    so each chunk stays under Telegram's message limit; see ``_CHUNK_CHAR_BUDGET``.

    Returns one chunk for small result sets, more only when the full digest
    (~33 hotels with deep links) exceeds one message. The title leads the first
    chunk only. Returns ``[]`` for no rows.
    """
    country_blocks: list[str] = []
    for _iso2, group in groupby(rows, key=lambda r: r.country_iso2):
        country_rows = list(group)
        country_name = country_rows[0].country_name or _iso2
        header = f"🌍 *{escape_markdown_v2(country_name)}*"
        lines = [
            _render_hotel_line(r, public_site_url=public_site_url)
            for r in sorted(country_rows, key=lambda r: r.rank)
        ]
        country_blocks.append(header + "\n" + "\n".join(lines))

    if not country_blocks:
        return []

    chunks: list[str] = []
    # Title leads the first chunk; subsequent chunks continue without it.
    current: list[str] = [_DIGEST_TITLE]

    for block in country_blocks:
        candidate = "\n\n".join([*current, block])
        if len(candidate) > _CHUNK_CHAR_BUDGET and current:
            chunks.append("\n\n".join(current))
            current = [block]
        else:
            current.append(block)

    if current:
        chunks.append("\n\n".join(current))

    return chunks


async def post_cheapest_digest() -> None:
    """Build and post the daily cheapest-tours digest. No-op when disabled."""
    if not _is_enabled():
        log.info("post_cheapest_digest.disabled", env=FEATURE_FLAG_ENV)
        return

    settings = get_settings()
    if not settings.telegram_enabled:
        log.warning(
            "post_cheapest_digest.skipped",
            reason="no_token",
            note="set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID to enable",
        )
        return

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text(cheapest_tours_sql()),
                {"per_country": PER_COUNTRY, "min_stars": MIN_STARS},
            )
        ).all()

    if not rows:
        log.info("post_cheapest_digest.no_rows")
        return

    chunks = render_digest(list(rows), public_site_url=settings.public_site_url)
    if not chunks:
        log.info("post_cheapest_digest.no_rows")
        return

    bot = make_bot(settings.telegram_bot_token or "")
    channel: str | int = settings.telegram_channel_id or ""
    # `-100...` channel ids are integers on the wire; coerce so diagnostics
    # show the canonical type (mirrors post_deals).
    if isinstance(channel, str) and channel.lstrip("-").isdigit():
        channel = int(channel)

    msg_ids: list[int] = []
    try:
        # ONE daily digest, transport-chunked on country boundaries when the
        # full list exceeds a single Telegram message. Previews disabled — a
        # digest of many links would otherwise render a giant preview card.
        for i, chunk in enumerate(chunks):
            msg_id = await broadcast_deal(
                bot,
                channel,
                chunk,
                disable_web_page_preview=True,
            )
            msg_ids.append(int(msg_id))
            if i < len(chunks) - 1:
                await asyncio.sleep(settings.telegram_send_delay_seconds)
    finally:
        # aiogram Bot owns an httpx session — close it or the loop warns.
        await bot.session.close()

    countries = len({r.country_iso2 for r in rows})
    log.info(
        "post_cheapest_digest.sent",
        msg_ids=msg_ids,
        chunks=len(chunks),
        hotels=len(rows),
        countries=countries,
    )
