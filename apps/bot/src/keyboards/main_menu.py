"""Reply keyboard — main menu.

Persistent under the text input; tapping a button sends its label as
plain text, which we route to the matching command via text-filter
handlers in `handlers/commands.py`.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Single source of truth for label ↔ command mapping. Used by
# handlers/commands.py to register text-filter dispatchers.
SEARCH = "🔍 Знайти тур"
DEALS = "🔥 Гарячі знижки"
DESTINATIONS = "🌍 Напрямки"
SUBSCRIBE = "🔔 Підписки"
PROFILE = "👤 Профіль"
HELP = "ℹ️ Допомога"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH), KeyboardButton(text=DEALS)],
            [KeyboardButton(text=DESTINATIONS), KeyboardButton(text=SUBSCRIBE)],
            [KeyboardButton(text=PROFILE), KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Виберіть розділ або введіть /команду",
    )
