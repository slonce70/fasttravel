"""Shared deal rendering semantics for Telegram surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from shared.deal_signals import get_deal_signal_copy
from shared.publishers.broadcast import escape_markdown_v2
from shared.text_uk import format_reviews, format_uah

HOTEL_DESCRIPTION_MAX_CHARS = 600


@dataclass(frozen=True)
class DealPriceSemantics:
    headline: str
    price_line: str
    why_line: str


def truncate_hotel_description(description: str) -> str:
    if len(description) <= HOTEL_DESCRIPTION_MAX_CHARS:
        return description
    clipped = description[: HOTEL_DESCRIPTION_MAX_CHARS - 3].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "..."


def render_deal_hotel_context(
    *,
    review_score: float | int | None,
    review_count: int | None,
    description_uk: str | None,
) -> str:
    """Return escaped MarkdownV2 hotel context lines for Telegram deal cards."""
    lines: list[str] = []
    reviews = int(review_count or 0)
    if review_score is not None and reviews > 0:
        lines.append(f"⭐ {float(review_score):.1f}/10 · {format_reviews(reviews)}")

    description = " ".join((description_uk or "").split())
    if description:
        lines.append(f"ℹ️ {truncate_hotel_description(description)}")

    if not lines:
        return ""
    return "".join(f"{escape_markdown_v2(line)}\n" for line in lines)


def render_deal_price_semantics(
    *,
    detection_method: str | None,
    discount_pct: float | int | None,
    price_uah: int | None,
    baseline_uah: int | None,
) -> DealPriceSemantics:
    """Return shared headline/price/why copy for one deal.

    `headline` and `price_line` are MarkdownV2-ready fragments; callers must
    not escape the full fragment again. `why_line` is plain copy because callers
    decide whether to wrap it in italics, buttons, or omit it. Keeping these
    semantics here prevents date-dip from drifting back into fake savings or
    strike-through copy.
    """
    discount = round(float(discount_pct or 0))
    price_int = int(price_uah or 0)
    baseline_int = int(baseline_uah or 0)
    savings = max(0, baseline_int - price_int)

    price_fmt = format_uah(price_int)
    baseline_fmt = format_uah(baseline_int)
    savings_fmt = format_uah(savings)
    signal = get_deal_signal_copy(detection_method)

    if signal.date_anomaly:
        # Show the local-regime typical price struck-through so the card answers
        # "cheaper than what?" — not just a bare percentage. The baseline is the
        # matched-side average of the surrounding dates within this date's own
        # price regime (see shared.deal_detection), so "звичайна ціна" ("the
        # usual price for these dates") is literally true — not a fake former
        # price. Only shown when there's a real gap.
        average = f" · звичайна ціна ~{baseline_fmt}~" if savings > 0 else ""
        return DealPriceSemantics(
            headline=f"📉 *На {discount}% дешевше за сусідні дати в цьому готелі*",
            price_line=f"💰 *{price_fmt}*{average}",
            why_line=signal.why_line,
        )
    if signal.peer_comparison:
        return DealPriceSemantics(
            headline=f"📊 *На {discount}% дешевше за схожі готелі*",
            price_line=f"💰 *{price_fmt}* · орієнтир схожих {baseline_fmt}",
            why_line=signal.why_line,
        )
    if signal.neutral_comparison:
        return DealPriceSemantics(
            headline=f"ℹ️ *На {discount}% нижче за ціновий орієнтир*",
            price_line=f"💰 *{price_fmt}* · орієнтир {baseline_fmt}",
            why_line=signal.why_line,
        )

    strikethrough = f" ~{baseline_fmt}~" if signal.strike_baseline and savings > 0 else ""
    return DealPriceSemantics(
        headline=f"🔥 *\\-{discount}% · економія {savings_fmt}*",
        price_line=f"💰 *{price_fmt}*{strikethrough}",
        why_line=signal.why_line,
    )
