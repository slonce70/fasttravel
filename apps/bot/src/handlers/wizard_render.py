"""Pure presentation helpers for the search wizard's results view.

Extracted from ``search_wizard.py`` so the handler module is left with FSM
dispatch + orchestration, and the "how a results page looks" concern lives
on its own — testable without constructing callbacks or FSM state.

Everything here is pure: given results data it returns text / keyboard
markup, with no Telegram, network, or FSM side effects.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shared.text_uk import plural_uk
from src.keyboards.filters import results_actions_kb


def format_results_header(*, total: int, page: int, total_pages: int) -> str:
    tour_word = plural_uk(total, "тур", "тури", "турів")
    return f"✅ Знайдено *{total}* {tour_word} · сторінка *{page}/{total_pages}*"


def result_link_rows(items: list[dict[str, Any]]) -> list[list[InlineKeyboardButton]]:
    """One row per hit: a single "🛒 Забронювати · <name>" button to the
    operator. The internal-site button (📖) was dropped because the web
    app at public_site_url returns 404 for /hotels/{slug} — keeping it
    only confused users. Re-add when apps/web/ is deployed (helper
    `_hotel_site_url` in search_wizard left in place for that day)."""
    rows: list[list[InlineKeyboardButton]] = []
    for h in items:
        deep_link = h.get("deep_link")
        if not deep_link:
            continue
        # 22-char name cap leaves room for the "🛒 Забронювати · " prefix
        # in Telegram's ~64-byte button label budget.
        name = (h.get("name_uk") or "Тур")[:22]
        rows.append([InlineKeyboardButton(text=f"🛒 Забронювати · {name}", url=deep_link)])
    return rows


def results_markup(
    *,
    chunk: list[dict[str, Any]],
    has_prev: bool,
    has_next: bool,
    page: int,
    total_pages: int,
    subscribed: bool,
) -> InlineKeyboardMarkup:
    detail_rows = result_link_rows(chunk)
    nav_kb = results_actions_kb(
        has_prev=has_prev,
        has_next=has_next,
        page=page,
        total_pages=total_pages,
        subscription_set=subscribed,
    )
    return InlineKeyboardMarkup(inline_keyboard=detail_rows + nav_kb.inline_keyboard)
