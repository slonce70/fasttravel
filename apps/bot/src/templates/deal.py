"""MarkdownV2 renderers for search results, deals, and hotel summaries.

Visual format stays in sync with the scheduler's `post_deals._render_deal`
on purpose — a user should see the same shape whether the post arrives
via channel broadcast, /deals list, search results, or personal alert.
Every DB-supplied field is piped through `escape_markdown_v2`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from shared.deal_signals import get_deal_signal_copy
from shared.publishers.broadcast import escape_markdown_v2
from shared.text_uk import format_meal_plan, format_nights, format_reviews


def _stars_str(stars: int | None) -> str:
    if not stars:
        return ""
    return "⭐" * int(stars)


def _format_uah(price: int | float | None) -> str:
    if price is None:
        return "—"
    # 35 200 ₴
    return f"{int(price):,}".replace(",", " ") + " ₴"


def _format_pct(pct: float | int | None) -> str:
    return f"{int(round(float(pct)))}" if pct is not None else "0"


def _format_hotel_context(row: dict[str, Any]) -> str:
    lines: list[str] = []
    review_score = row.get("review_score")
    review_count = int(row.get("review_count") or 0)
    if review_score is not None and review_count > 0:
        lines.append(f"⭐ {float(review_score):.1f}/10 · {format_reviews(review_count)}")

    description = " ".join(str(row.get("description_uk") or "").split())
    if description:
        if len(description) > 140:
            description = description[:137].rstrip() + "..."
        lines.append(f"ℹ️ {description}")

    if not lines:
        return ""
    return "".join(f"{escape_markdown_v2(line)}\n" for line in lines)


def _format_date(value: str | date | datetime) -> str:
    """Render '14 черв.' style. Accepts ISO string or date/datetime."""
    if isinstance(value, str):
        try:
            d = date.fromisoformat(value.split("T", 1)[0])
        except ValueError:
            return value
    elif isinstance(value, datetime):
        d = value.date()
    else:
        d = value
    months = (
        "січ.",
        "лют.",
        "бер.",
        "квіт.",
        "трав.",
        "черв.",
        "лип.",
        "серп.",
        "вер.",
        "жовт.",
        "лист.",
        "груд.",
    )
    return f"{d.day} {months[d.month - 1]}"


def render_search_hit(hit: dict[str, Any]) -> str:
    """One search-result card (no buttons — those come from a keyboard).

    Hits come from `/api/search` paginated payload — see SearchResultItem
    in apps/api/src/schemas/search.py.
    """
    name = escape_markdown_v2(hit.get("name_uk") or "Готель")
    stars = _stars_str(hit.get("stars"))
    destination = escape_markdown_v2(hit.get("destination_name") or "")
    min_price = _format_uah(hit.get("min_price_uah"))
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
    stars = _stars_str(row.get("hotel_stars"))
    destination = escape_markdown_v2(row.get("destination_name") or "")
    check_in = escape_markdown_v2(_format_date(row.get("check_in")))
    nights = row.get("nights") or 7
    meal = escape_markdown_v2(format_meal_plan(row.get("meal_plan")))
    price_int = int(row.get("price_uah") or 0)
    baseline_int = int(row.get("baseline_p50") or 0)
    savings = max(0, baseline_int - price_int)
    price_fmt = escape_markdown_v2(_format_uah(price_int))
    baseline_fmt = escape_markdown_v2(_format_uah(baseline_int))
    savings_fmt = escape_markdown_v2(_format_uah(savings))

    strikethrough = f"~{baseline_fmt}~" if savings > 0 else ""

    signal = get_deal_signal_copy(row.get("detection_method"))
    why = signal.why_line
    why_block = f"\n_{escape_markdown_v2(why)}_" if why else ""
    if signal.peer_comparison:
        headline = f"📊 *{discount}% дешевше за схожі готелі*\n"
        price_line = f"💰 *{price_fmt}* · орієнтир схожих {baseline_fmt}"
    else:
        headline = f"🔥 *\\-{discount}% · економія {savings_fmt}*\n"
        price_line = f"💰 *{price_fmt}* {strikethrough}".rstrip()

    return (
        headline
        + f"🏨 *{name}* {stars}".rstrip()
        + "\n"
        + (f"📍 {destination}\n" if destination else "")
        + _format_hotel_context(row)
        + f"📅 {check_in} · {escape_markdown_v2(format_nights(int(nights)))} · {meal}\n"
        + price_line
        + why_block
    )
