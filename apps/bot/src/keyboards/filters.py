"""Filter keyboards for the wizard.

Each step exposes a small set of preset buttons + a «Назад» back-button.
Callback data uses a short `step:value` shape so handlers can route
without parsing free text.

  nights:  n:7..n:14, n:any, n:back
  when:    w:soon, w:month, w:season, w:back
  budget:  b:30000, b:50000, b:80000, b:120000, b:any, b:back
  meal:    m:AI, m:HB, m:BB, m:RO, m:any, m:back
  stars:   s:3, s:4, s:5, s:any, s:back
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _back_row(prefix: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="◀ Назад", callback_data=f"{prefix}:back")]


def nights_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="7 ноч ⭐", callback_data="n:7"),
                InlineKeyboardButton(text="8 ноч", callback_data="n:8"),
                InlineKeyboardButton(text="9 ноч", callback_data="n:9"),
                InlineKeyboardButton(text="10 ноч", callback_data="n:10"),
            ],
            [
                InlineKeyboardButton(text="11 ноч", callback_data="n:11"),
                InlineKeyboardButton(text="12 ноч", callback_data="n:12"),
                InlineKeyboardButton(text="13 ноч", callback_data="n:13"),
                InlineKeyboardButton(text="14 ноч", callback_data="n:14"),
            ],
            [InlineKeyboardButton(text="🤷 Будь-яка", callback_data="n:any")],
            _back_row("n"),
        ]
    )


def when_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Найближчі тижні", callback_data="w:soon")],
            [InlineKeyboardButton(text="📅 Через місяць", callback_data="w:month")],
            [InlineKeyboardButton(text="🌴 Через 2-3 місяці", callback_data="w:season")],
            [InlineKeyboardButton(text="🤷 Без різниці", callback_data="w:any")],
            _back_row("w"),
        ]
    )


def budget_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="до 30 000 ₴", callback_data="b:30000"),
                InlineKeyboardButton(text="30-50 тис", callback_data="b:50000"),
            ],
            [
                InlineKeyboardButton(text="50-80 тис", callback_data="b:80000"),
                InlineKeyboardButton(text="80-120 тис", callback_data="b:120000"),
            ],
            [InlineKeyboardButton(text="Преміум 120+", callback_data="b:premium")],
            [InlineKeyboardButton(text="Без обмежень", callback_data="b:any")],
            _back_row("b"),
        ]
    )


def meal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Все включено (AI) 🍹", callback_data="m:AI")],
            [InlineKeyboardButton(text="Напівпансіон (HB)", callback_data="m:HB")],
            [InlineKeyboardButton(text="Сніданок (BB)", callback_data="m:BB")],
            [InlineKeyboardButton(text="Без харчування", callback_data="m:RO")],
            [InlineKeyboardButton(text="🤷 Будь-яке", callback_data="m:any")],
            _back_row("m"),
        ]
    )


def stars_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3⭐+", callback_data="s:3"),
                InlineKeyboardButton(text="4⭐+", callback_data="s:4"),
                InlineKeyboardButton(text="5⭐", callback_data="s:5"),
            ],
            [InlineKeyboardButton(text="🤷 Будь-яка", callback_data="s:any")],
            _back_row("s"),
        ]
    )


def results_actions_kb(
    *,
    has_prev: bool,
    has_next: bool,
    page: int,
    total_pages: int,
    subscription_set: bool = False,
) -> InlineKeyboardMarkup:
    """Pagination + action row for the results page.

    page/total_pages are 1-based and shown to the user (`Сторінка 2/5`).
    The «Підписатись» button is only enabled when the user landed on
    real results (otherwise it would store an empty filter set).
    """
    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="◀", callback_data="res:prev"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="res:noop"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="▶", callback_data="res:next"))

    rows: list[list[InlineKeyboardButton]] = [
        nav_row,
        [InlineKeyboardButton(text="🔄 Новий пошук", callback_data="res:restart")],
    ]
    if not subscription_set:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔔 Алерт за цими фільтрами",
                    callback_data="res:subscribe",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
