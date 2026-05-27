"""Country selection keyboard for the search wizard.

Two-column grid. Each row is `[country_a][country_b]`; rows are sorted
by `hotel_count DESC` (the API returns them that way already). Country
emojis live in `_FLAG_BY_ISO` so the UI stays static-deterministic even
if the API drops or adds destinations.

Callback data shape: `cc:TR` (Country Code → search step). Aiogram caps
callback_data at 64 bytes; iso2 + a 3-char prefix sits well under it.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Hand-mapped emoji flags. Telegram clients render them natively.
_FLAG_BY_ISO: dict[str, str] = {
    "TR": "🇹🇷",
    "EG": "🇪🇬",
    "AE": "🇦🇪",
    "GR": "🇬🇷",
    "ES": "🇪🇸",
    "BG": "🇧🇬",
    "TH": "🇹🇭",
    "CY": "🇨🇾",
    "HR": "🇭🇷",
    "ME": "🇲🇪",
    "MV": "🇲🇻",
    "IT": "🇮🇹",
    "TN": "🇹🇳",
    "DO": "🇩🇴",
}


def country_emoji(iso2: str) -> str:
    return _FLAG_BY_ISO.get(iso2.upper(), "📍")


def countries_kb(
    destinations: list[dict[str, Any]],
    *,
    callback_prefix: str = "cc",
    show_counts: bool = True,
    include_cancel: bool = True,
) -> InlineKeyboardMarkup:
    """Build a 2-col country picker from a destinations list.

    `destinations` is the raw payload from `GET /api/destinations` — each
    item has `country_iso2`, `name_uk`, and `hotel_count`. Empty/zero
    countries are filtered out so the wizard never offers something
    `/search` will return 0 results for.
    """
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for d in destinations:
        if not show_counts or d.get("hotel_count", 0) > 0:
            iso = d["country_iso2"]
            label = f"{country_emoji(iso)} {d['name_uk']}"
            if show_counts:
                label += f" ({d['hotel_count']})"
            current.append(
                InlineKeyboardButton(text=label, callback_data=f"{callback_prefix}:{iso}")
            )
            if len(current) == 2:
                rows.append(current)
                current = []
    if current:
        rows.append(current)
    if include_cancel:
        rows.append(
            [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{callback_prefix}:cancel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
