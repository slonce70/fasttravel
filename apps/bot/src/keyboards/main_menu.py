"""Reply keyboard — main menu.

Persistent under the text input; tapping a button sends its label as
plain text, which we route to the matching command via text-filter
handlers in `handlers/commands.py`.

Layout choice (task clusters):
  Row 1: SEARCH + DESTINATIONS      — intent tools: the search wizard and
                                       the country catalogue.
  Row 2: BEST + DEALS + CHEAP        — the three browse feeds in one
                                       scannable cluster (top now / hot
                                       tours / cheapest by country).
  Row 3: SUBSCRIBE + PROFILE + HELP  — account.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Single source of truth for label ↔ command mapping. Used by
# handlers/commands.py to register text-filter dispatchers.
BEST = "🏆 Топ зараз"
SEARCH = "🔍 Знайти тур"
DEALS = "🔥 Гарячі тури"
CHEAP = "💰 Найдешевші тури"
DESTINATIONS = "🌍 Напрямки"
SUBSCRIBE = "🔔 Мої підписки"
PROFILE = "👤 Профіль"
HELP = "ℹ️ Допомога"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH), KeyboardButton(text=DESTINATIONS)],
            [
                KeyboardButton(text=BEST),
                KeyboardButton(text=DEALS),
                KeyboardButton(text=CHEAP),
            ],
            [
                KeyboardButton(text=SUBSCRIBE),
                KeyboardButton(text=PROFILE),
                KeyboardButton(text=HELP),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Виберіть розділ або введіть /команду",
    )
