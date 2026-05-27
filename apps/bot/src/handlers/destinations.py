"""/destinations — country grid + per-country drill-down.

Top-level: list every country (with at least 1 priced hotel) as a single-
column reply with a count badge. Tapping a country shows:
  • top deals in that country (up to 3)
  • a "Знайти тури" button that starts the search wizard with the country
    pre-filled.

Same callback prefix policy as the wizard: `ds:TR` for drill-down,
`ds:back` to return to the country list.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from shared.publishers.broadcast import escape_markdown_v2
from shared.text_uk import format_hotels
from src.config import get_settings
from src.infra.api_client import ApiError, get_deals, get_destinations
from src.infra.logging import get_logger
from src.keyboards.countries import country_emoji, country_name_uk
from src.keyboards.main_menu import main_menu_kb
from src.states.search import SearchState
from src.templates.deal import render_deal

router = Router(name="destinations")
log = get_logger(__name__)

_MAX_DRILL_DEALS = 3


def _countries_list_kb(destinations: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """One country per row so the count badge stays readable."""
    rows: list[list[InlineKeyboardButton]] = []
    for d in destinations:
        if d.get("hotel_count", 0) <= 0:
            continue
        iso = d["country_iso2"]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{country_emoji(iso)} {d['name_uk']}   ·   {format_hotels(int(d['hotel_count']))}",
                    callback_data=f"ds:{iso}",
                )
            ]
        )
    settings = get_settings()
    if not rows and settings.public_site_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Сайт із календарем цін",
                    url=settings.public_site_url,
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _drill_kb(iso: str) -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔍 Знайти тури в цю країну",
                callback_data=f"ds:search:{iso}",
            )
        ]
    ]
    if settings.public_site_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🌐 Всі готелі на сайті",
                    url=f"{settings.public_site_url.rstrip('/')}/destinations/{iso.lower()}?utm_source=tg_bot",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀ До списку країн", callback_data="ds:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_destinations(message: Message) -> None:
    try:
        destinations = await get_destinations()
    except ApiError:
        await message.answer(
            "Сервіс тимчасово недоступний\\. Спробуйте за хвилину\\.",
            reply_markup=main_menu_kb(),
        )
        return

    if not destinations:
        await message.answer(
            "Поки немає доступних напрямків\\. Завітайте пізніше\\.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        "*🌍 Куди літаємо\\?*\n\nНатисніть країну, щоб побачити топ\\-знижки та готелі\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_countries_list_kb(destinations),
    )


@router.message(Command("destinations"))
async def cmd_destinations(message: Message) -> None:
    await show_destinations(message)


@router.callback_query(F.data == "ds:back")
async def cb_back(query: CallbackQuery) -> None:
    try:
        destinations = await get_destinations()
    except ApiError:
        await query.answer("Сервіс недоступний", show_alert=False)
        return
    await query.message.edit_text(
        "*🌍 Куди літаємо\\?*\n\nНатисніть країну, щоб побачити топ\\-знижки та готелі\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_countries_list_kb(destinations),
    )
    await query.answer()


@router.callback_query(F.data.startswith("ds:search:"))
async def cb_search_in_country(query: CallbackQuery, state: FSMContext) -> None:
    iso = (query.data or "").split(":", 2)[2]
    # Hand off to the wizard with country pre-filled (skip choosing_country step)
    await state.clear()
    name = country_name_uk(iso)
    await state.update_data(country=iso, country_emoji=country_emoji(iso), country_name=name)
    await state.set_state(SearchState.choosing_nights)
    from src.keyboards.filters import nights_kb

    await query.message.edit_text(
        f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · скільки ночей\\? 🌙",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=nights_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("ds:"))
async def cb_country_drill(query: CallbackQuery) -> None:
    iso = (query.data or "").split(":", 1)[1]
    if iso in {"back"} or iso.startswith("search:"):
        return  # already handled by other callbacks

    try:
        deals_payload = await get_deals(limit=_MAX_DRILL_DEALS, country=iso)
    except ApiError:
        await query.answer("Сервіс недоступний", show_alert=False)
        return

    items: list[dict[str, Any]] = deals_payload.get("items", [])
    header = f"{country_emoji(iso)} *{escape_markdown_v2(country_name_uk(iso))}* · топ знижок"
    if not items:
        body = "_Зараз немає активних знижок у цій країні\\._\nСпробуйте «🔍 Знайти тури» нижче\\."
    else:
        body = "\n\n— · — · —\n\n".join(render_deal(d) for d in items)
    text = f"{header}\n\n{body}"

    try:
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=_drill_kb(iso),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("destinations.edit_skip", error=str(exc))
    await query.answer()
