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

from shared.site_urls import public_hotel_url
from shared.text_uk import plural_uk
from src.keyboards.filters import results_actions_kb

# Deterministic step order for the 6-step search wizard. /help advertises a
# "майстер з 6 кроків", so each prompt is prefixed with its position
# («Крок k/6 · …») to match that promise. Kept here, pure and testable,
# rather than scattering literal indices across the handler.
WIZARD_STEPS: tuple[str, ...] = (
    "country",
    "nights",
    "when",
    "budget",
    "meal",
    "stars",
)
WIZARD_STEP_COUNT = len(WIZARD_STEPS)


def step_prefix(step: str) -> str:
    """Return the «Крок k/6 · » marker for a named wizard step.

    Unknown steps return an empty prefix so a future step rename degrades to
    the bare prompt rather than raising mid-flow.
    """
    try:
        index = WIZARD_STEPS.index(step) + 1
    except ValueError:
        return ""
    return f"Крок {index}/{WIZARD_STEP_COUNT} · "


def format_results_header(
    *, total: int, page: int, total_pages: int, shown: int | None = None
) -> str:
    """Results-page header.

    ``total`` is the API's full COUNT(*) of matching hotels, but only the
    first ``shown`` items are cached/browsable (the wizard pulls a single
    capped page and never refetches on page-turn). When the catalog holds
    more matches than we fetched, say so honestly instead of implying all
    ``total`` tours are reachable through the pager.
    """
    tour_word = plural_uk(total, "тур", "тури", "турів")
    base = f"✅ Знайдено *{total}* {tour_word}"
    if shown is not None and total > shown:
        base += f" · показано перші *{shown}*"
    return f"{base} · сторінка *{page}/{total_pages}*"


def result_link_rows(
    items: list[dict[str, Any]], *, site_base_url: str | None = None
) -> list[list[InlineKeyboardButton]]:
    """One row per hit with up to two buttons: the operator booking deep link
    and an internal price-calendar link to ``/hotels/{slug}`` on the public
    site (``apps/web/src/app/hotels/[slug]``).

    A hit with no operator deep link is still shown when its slug resolves to a
    site URL; a hit with neither is dropped (no empty button rows). With no
    ``site_base_url`` configured, falls back to operator-only.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for h in items:
        deep_link = h.get("deep_link")
        # 22-char name cap leaves room for the emoji/prefix in Telegram's
        # ~64-byte button-label budget.
        name = (h.get("name_uk") or "Тур")[:22]
        site_url = public_hotel_url(site_base_url, h.get("canonical_slug"), medium="wizard")

        buttons: list[InlineKeyboardButton] = []
        if deep_link:
            buttons.append(InlineKeyboardButton(text=f"🛒 Забронювати · {name}", url=deep_link))
        if site_url:
            # Paired with the named booking button the site button stays terse;
            # a site-only hit carries the name for per-hit disambiguation.
            site_text = "📖 Деталі" if deep_link else f"📖 {name}"
            buttons.append(InlineKeyboardButton(text=site_text, url=site_url))
        if buttons:
            rows.append(buttons)
    return rows


def results_markup(
    *,
    chunk: list[dict[str, Any]],
    has_prev: bool,
    has_next: bool,
    page: int,
    total_pages: int,
    subscribed: bool,
    site_base_url: str | None = None,
) -> InlineKeyboardMarkup:
    detail_rows = result_link_rows(chunk, site_base_url=site_base_url)
    nav_kb = results_actions_kb(
        has_prev=has_prev,
        has_next=has_next,
        page=page,
        total_pages=total_pages,
        subscription_set=subscribed,
    )
    return InlineKeyboardMarkup(inline_keyboard=detail_rows + nav_kb.inline_keyboard)
