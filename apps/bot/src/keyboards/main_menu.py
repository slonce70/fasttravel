"""Reply keyboard — main menu.

Persistent under the text input; tapping a button sends its label as
plain text, which we route to the matching command via text-filter
handlers in `handlers/commands.py`.

Layout choice:
  Row 1: BEST + SEARCH       — the two "buy intent" actions; strongest
                               current variants and the full search wizard.
  Row 2: DEALS + CHEAP        — browse the discount feed vs. the absolute
                               cheapest tours by country.
  Row 3: DESTINATIONS         — country catalogue.
  Row 4: SUBSCRIBE + PROFILE + HELP — long-tail / account.

`BEST` leads because the product's main job is "show me the best options" —
matches the channel post style and the /best command.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Single source of truth for label ↔ command mapping. Used by
# handlers/commands.py to register text-filter dispatchers.
BEST = "🏆 ТОП варіанти"
SEARCH = "🔍 Знайти тур"
DEALS = "🔥 Усі варіанти"
CHEAP = "🔥 Найдешевші тури"
DESTINATIONS = "🌍 Напрямки"
SUBSCRIBE = "🔔 Підписки на варіанти"
PROFILE = "👤 Профіль"
HELP = "ℹ️ Допомога"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BEST), KeyboardButton(text=SEARCH)],
            [KeyboardButton(text=DEALS), KeyboardButton(text=CHEAP)],
            [KeyboardButton(text=DESTINATIONS)],
            [
                KeyboardButton(text=SUBSCRIBE),
                KeyboardButton(text=PROFILE),
                KeyboardButton(text=HELP),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Виберіть розділ або введіть /команду",
    )
