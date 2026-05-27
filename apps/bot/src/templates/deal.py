"""MarkdownV2 renderers for search results, deals, and hotel summaries.

Visual format stays in sync with the scheduler's `post_deals._render_deal`
on purpose — a user should see the same shape whether the post arrives
via channel broadcast, /deals list, search results, or personal alert.
Every DB-supplied field is piped through `escape_markdown_v2`.
"""

from __future__ import annotations

from typing import Any

from shared.deal_signals import get_deal_signal_copy
from shared.publishers.broadcast import escape_markdown_v2
from shared.text_uk import (
    format_date_short,
    format_meal_plan,
    format_nights,
    format_reviews,
    format_stars,
    format_uah,
)

HOTEL_DESCRIPTION_MAX_CHARS = 600


def _format_pct(pct: float | int | None) -> str:
    return f"{int(round(float(pct)))}" if pct is not None else "0"


def _truncate_description(description: str) -> str:
    if len(description) <= HOTEL_DESCRIPTION_MAX_CHARS:
        return description
    clipped = description[: HOTEL_DESCRIPTION_MAX_CHARS - 3].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "..."


def _format_hotel_context(row: dict[str, Any]) -> str:
    lines: list[str] = []
    review_score = row.get("review_score")
    review_count = int(row.get("review_count") or 0)
    if review_score is not None and review_count > 0:
        lines.append(f"⭐ {float(review_score):.1f}/10 · {format_reviews(review_count)}")

    description = " ".join(str(row.get("description_uk") or "").split())
    if description:
        lines.append(f"ℹ️ {_truncate_description(description)}")

    if not lines:
        return ""
    return "".join(f"{escape_markdown_v2(line)}\n" for line in lines)


def render_search_hit(hit: dict[str, Any]) -> str:
    """One search-result card (no buttons — those come from a keyboard).

    Hits come from `/api/search` paginated payload — see SearchResultItem
    in apps/api/src/schemas/search.py.
    """
    name = escape_markdown_v2(hit.get("name_uk") or "Готель")
    stars = format_stars(hit.get("stars"))
    destination = escape_markdown_v2(hit.get("destination_name") or "")
    min_price = format_uah(hit.get("min_price_uah"))
    review_score = hit.get("review_score")
    review_count = hit.get("review_count") or 0

    lines = [f"🏨 *{name}* {stars}".rstrip()]
    if destination:
        lines.append(f"📍 {destination}")
    lines.append(f"💰 від *{escape_markdown_v2(min_price)}*")
    if hit.get("nights_fallback") and hit.get("requested_nights") and hit.get("effective_nights"):
        effective = escape_markdown_v2(format_nights(int(hit["effective_nights"])))
        requested = escape_markdown_v2(format_nights(int(hit["requested_nights"])))
        lines.append(f"⚠️ ціна за {effective}\\, не за {requested}")
    if review_score is not None and review_count > 0:
        score_txt = escape_markdown_v2(f"{float(review_score):.1f}")
        lines.append(f"⭐ {score_txt}/10 · {escape_markdown_v2(format_reviews(int(review_count)))}")
    return "\n".join(lines)


def render_deal(row: dict[str, Any]) -> str:
    """One deal card — same shape used by the scheduler post_deals job
    (kept visually consistent on purpose). Renders DealOut JSON.

    Layout:
        🔥 *-37% · економія 12 500 ₴*
        🏨 *Hotel Name* ⭐⭐⭐⭐
        📍 Antalya
        📅 14 черв. · 7 ночей · Все включено
        💰 *21 000 ₴* ~33 500 ₴~
        _📉 Аномально дешева дата у цьому готелі_

    All four blocks (headline, identity, dates, price) sit on their own
    rows so the card scans in <2 seconds even on a phone — the channel
    user's attention budget is small.
    """
    discount = _format_pct(row.get("discount_pct"))
    name = escape_markdown_v2(row.get("hotel_name_uk") or "Готель")
    stars = format_stars(row.get("hotel_stars"))
    destination = escape_markdown_v2(row.get("destination_name") or "")
    check_in = escape_markdown_v2(format_date_short(row.get("check_in") or ""))
    nights = row.get("nights") or 7
    meal = escape_markdown_v2(format_meal_plan(row.get("meal_plan")))
    price_int = int(row.get("price_uah") or 0)
    baseline_int = int(row.get("baseline_p50") or 0)
    savings = max(0, baseline_int - price_int)
    price_fmt = escape_markdown_v2(format_uah(price_int))
    baseline_fmt = escape_markdown_v2(format_uah(baseline_int))
    savings_fmt = escape_markdown_v2(format_uah(savings))

    signal = get_deal_signal_copy(row.get("detection_method"))
    why = signal.why_line
    why_block = f"\n_{escape_markdown_v2(why)}_" if why else ""
    if signal.date_anomaly:
        # baseline = median of neighbouring check-in dates → no strikethrough,
        # no "економія", since the user can't keep that "saving" with THIS
        # booking; they'd have to pick a different date.
        headline = f"📉 *На {discount}% дешевше за сусідні дати в цьому готелі*\n"
        price_line = f"💰 *{price_fmt}*"
    elif signal.peer_comparison:
        headline = f"📊 *{discount}% дешевше за схожі готелі*\n"
        price_line = f"💰 *{price_fmt}* · орієнтир схожих {baseline_fmt}"
    else:
        strikethrough = f"~{baseline_fmt}~" if savings > 0 else ""
        headline = f"🔥 *\\-{discount}% · економія {savings_fmt}*\n"
        price_line = f"💰 *{price_fmt}* {strikethrough}".rstrip()

    deep_link = row.get("deep_link")
    booking_line = ""
    if deep_link:
        safe_url = deep_link.replace("\\", "\\\\").replace(")", "\\)")
        booking_line = f"\n🛒 [Переглянути пропозицію →]({safe_url})"

    return (
        headline
        + f"🏨 *{name}* {stars}".rstrip()
        + "\n"
        + (f"📍 {destination}\n" if destination else "")
        + _format_hotel_context(row)
        + f"📅 {check_in} · {escape_markdown_v2(format_nights(int(nights)))} · {meal}\n"
        + price_line
        + why_block
        + booking_line
    )
