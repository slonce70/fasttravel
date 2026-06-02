"""MarkdownV2 renderer for the «Найдешевші тури» digest.

Deliberately separate from `templates.deal`: this surface shows the
*absolute-cheap* price («ціна від»), NEVER a discount. No «−X%», no
struck-through baseline, no «знижка» — that copy belongs to the anomaly
deal channel only (see docs/superpowers/specs/2026-06-03-cheapest-tours-design.md).

Renders `CheapestTourOut` rows (see the API contract): `hotel_name`,
`stars`, `country_name`/`country_iso2`, `check_in`, `nights`, `meal_plan`,
`price_uah`, `deep_link` (str|null), `review_score` (float|null),
`review_count`, `rank`. Every DB-supplied field is escaped.

Length budget: a TOP-3 × many-country digest can exceed Telegram's
4096-char message cap, so the digest is built country-by-country and stops
before the budget runs out. The cap is measured on the *parsed* length
(Telegram counts text "after entities parsing": hidden link URLs and the
MarkdownV2 bold/escape markers don't count), so we don't truncate countries
that would actually fit. When countries are dropped, the footer points to
the website so a user never concludes a missing destination has no tours.
"""

from __future__ import annotations

import re
from itertools import groupby
from typing import Any

from shared.publishers.broadcast import (
    escape_markdown_v2,
    escape_markdown_v2_url,
)
from shared.text_uk import (
    format_date_short,
    format_meal_plan,
    format_nights,
    format_reviews,
    format_stars,
    format_uah,
)

# Telegram's hard message cap is 4096; keep a margin for safety.
_MAX_PARSED_LEN = 3800

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def telegram_parsed_len(text: str) -> int:
    """Estimate the length Telegram counts against its 4096 cap.

    Telegram measures the message "after entities parsing" in UTF-16 code
    units: the hidden URL in ``[label](url)`` doesn't count (only the
    label), and the MarkdownV2 ``*`` bold markers / ``\\`` escapes don't
    count either. Emoji are 2 UTF-16 units. Counting raw ``len()`` would
    massively over-count our many long deep-link URLs and truncate
    countries that actually fit.
    """
    stripped = _LINK_RE.sub(r"\1", text)  # keep link label, drop the URL
    stripped = stripped.replace("\\", "").replace("*", "")
    return len(stripped.encode("utf-16-le")) // 2


def render_cheap_card(row: dict[str, Any]) -> str:
    """One cheapest-tour card. Price line is the ONLY price claim («ціна від»).

    Layout:
        🏨 *Hotel Name* ⭐⭐⭐
        📅 6 черв. · 7 ночей · Без харчування
        💰 ціна від *18 210 ₴*
        ⭐ 9.2/10 · 4 відгуки
        🛒 [Переглянути →](url)
    """
    name = escape_markdown_v2(row.get("hotel_name") or "Готель")
    stars = format_stars(row.get("stars"))
    check_in = escape_markdown_v2(format_date_short(row.get("check_in") or ""))
    nights = row.get("nights") or 7
    meal = escape_markdown_v2(format_meal_plan(row.get("meal_plan")))
    price = escape_markdown_v2(format_uah(row.get("price_uah")))

    lines = [
        f"🏨 *{name}* {stars}".rstrip(),
        f"📅 {check_in} · {escape_markdown_v2(format_nights(int(nights)))} · {meal}",
        f"💰 ціна від *{price}*",
    ]

    review_score = row.get("review_score")
    review_count = row.get("review_count") or 0
    if review_score is not None and review_count > 0:
        score_txt = escape_markdown_v2(f"{float(review_score):.1f}")
        reviews_txt = escape_markdown_v2(format_reviews(int(review_count)))
        lines.append(f"⭐ {score_txt}/10 · {reviews_txt}")

    deep_link = row.get("deep_link")
    if deep_link:
        lines.append(f"🛒 [Переглянути →]({escape_markdown_v2_url(deep_link)})")

    return "\n".join(lines)


def _render_country_block(rows: list[dict[str, Any]]) -> str:
    country = escape_markdown_v2(rows[0].get("country_name") or "Інші напрямки")
    cards = "\n\n".join(render_cheap_card(r) for r in rows)
    return f"📍 *{country}*\n\n{cards}"


def render_cheap_digest(
    rows: list[dict[str, Any]],
    *,
    site_cheap_url: str | None = None,
) -> str:
    """Group the flat ranked list by country and render the digest.

    Rows arrive pre-sorted contiguous by country (country_name, rank,
    hotel_id), so a single ``groupby`` pass groups them cleanly. Countries
    are appended while the parsed length stays under budget; at least one
    country is always shown. Honest copy throughout: «ціна від», never
    «знижка».
    """
    header = "🔥 *Найдешевші тури по напрямках*"

    if not rows:
        empty = (
            "Зараз немає свіжих варіантів\\. Завітайте трохи пізніше або " "перегляньте /search\\."
        )
        return f"{header}\n\n{empty}"

    country_blocks = [
        _render_country_block(list(group))
        for _iso2, group in groupby(rows, key=lambda r: r.get("country_iso2"))
    ]
    total_countries = len(country_blocks)

    base_footer = "_Ціни оновлюються двічі на день\\. «ціна від» — реальна стартова ціна туру\\._"
    sep = "\n\n— · — · —\n\n"

    shown: list[str] = []
    # Reserve room for header + footer so the budget is for country blocks.
    reserve = telegram_parsed_len(f"{header}\n\n{sep}\n\n{base_footer}")
    used = reserve
    for block in country_blocks:
        cost = telegram_parsed_len(block) + telegram_parsed_len(sep)
        # Always keep at least one country, even if it alone is large.
        if shown and used + cost > _MAX_PARSED_LEN:
            break
        shown.append(block)
        used += cost

    truncated = len(shown) < total_countries
    footer = base_footer
    if truncated:
        more = "Повний список напрямків — на сайті\\."
        if site_cheap_url:
            more = f"[Усі напрямки на сайті →]({escape_markdown_v2_url(site_cheap_url)})"
        footer = f"{more}\n{base_footer}"

    body = sep.join(shown)
    return f"{header}\n\n{body}\n\n{footer}"
