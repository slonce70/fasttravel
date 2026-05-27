"""Search wizard: country → nights → when → budget → meal → stars → results.

State machine lives in `src.states.search.SearchState`. Each step renders
its keyboard, accepts a callback, persists the choice via `state.update_data`,
and advances to the next state. Results page calls `/api/search` once and
paginates through the cached list.

Cancellation: `cc:cancel` or any free-text on a state clears FSM + sends
the user back to the main menu.
"""

from __future__ import annotations

from datetime import date, timedelta
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
from shared.text_uk import plural_uk
from src.config import get_settings
from src.infra.api_client import ApiError, get_destinations, search_hotels
from src.infra.db import add_subscription, ensure_subscriber
from src.infra.logging import get_logger
from src.keyboards.countries import countries_kb, country_emoji, country_name_uk
from src.keyboards.filters import (
    budget_kb,
    meal_kb,
    nights_kb,
    results_actions_kb,
    stars_kb,
    when_kb,
)
from src.keyboards.main_menu import main_menu_kb
from src.states.search import SearchState
from src.templates.deal import render_search_hit

router = Router(name="search_wizard")
log = get_logger(__name__)

_RESULTS_KEY = "results"
_PAGE_KEY = "page"
_PAGE_SIZE = 5


def _format_results_header(*, total: int, page: int, total_pages: int) -> str:
    tour_word = plural_uk(total, "тур", "тури", "турів")
    return f"✅ Знайдено *{total}* {tour_word} · сторінка *{page}/{total_pages}*"


def _hotel_site_url(slug: str | None, medium: str = "wizard") -> str | None:
    if not slug:
        return None
    settings = get_settings()
    if not settings.public_site_url:
        return None
    return (
        f"{settings.public_site_url.rstrip('/')}/hotels/{slug}"
        f"?utm_source=tg_bot&utm_medium={medium}"
    )


def _result_link_rows(items: list[dict[str, Any]]) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for h in items:
        buttons: list[InlineKeyboardButton] = []
        site_url = _hotel_site_url(h.get("canonical_slug"))
        if site_url:
            buttons.append(
                InlineKeyboardButton(
                    text=f"📖 {h.get('name_uk', 'Готель')[:24]}",
                    url=site_url,
                )
            )
        deep_link = h.get("deep_link")
        if deep_link:
            buttons.append(
                InlineKeyboardButton(
                    text=f"🛒 {h.get('name_uk', 'Тур')[:24]}",
                    url=deep_link,
                )
            )
        if buttons:
            rows.append(buttons)
    return rows


async def start_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
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

    await state.set_state(SearchState.choosing_country)
    await message.answer(
        "*Куди летимо\\?* ✈️\n\nВиберіть країну\\:",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations),
    )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    await start_wizard(message, state)


@router.callback_query(F.data.startswith("cc:"), SearchState.choosing_country)
async def cb_country(query: CallbackQuery, state: FSMContext) -> None:
    iso = query.data.split(":", 1)[1] if query.data else ""
    if iso == "cancel":
        await state.clear()
        await query.message.edit_text("Пошук скасовано\\.")
        await query.answer()
        return

    name = country_name_uk(iso)
    await state.update_data(country=iso, country_emoji=country_emoji(iso), country_name=name)
    await state.set_state(SearchState.choosing_nights)
    await query.message.edit_text(
        f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · скільки ночей\\? 🌙",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=nights_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("n:"), SearchState.choosing_nights)
async def cb_nights(query: CallbackQuery, state: FSMContext) -> None:
    value = query.data.split(":", 1)[1] if query.data else ""
    if value == "back":
        await _go_back_to_country(query, state)
        return
    nights = None if value == "any" else int(value)
    await state.update_data(nights=nights)
    await state.set_state(SearchState.choosing_when)
    await query.message.edit_text(
        "*Коли заїзд\\?* 📅",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=when_kb(),
    )
    await query.answer()


_WHEN_OFFSETS_DAYS: dict[str, int | None] = {
    "soon": 7,
    "month": 30,
    "season": 60,
    "any": None,
}


@router.callback_query(F.data.startswith("w:"), SearchState.choosing_when)
async def cb_when(query: CallbackQuery, state: FSMContext) -> None:
    value = query.data.split(":", 1)[1] if query.data else ""
    if value == "back":
        await state.set_state(SearchState.choosing_nights)
        await query.message.edit_text(
            "*Скільки ночей\\?* 🌙",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=nights_kb(),
        )
        await query.answer()
        return

    offset = _WHEN_OFFSETS_DAYS.get(value)
    check_in = (date.today() + timedelta(days=offset)).isoformat() if offset else None
    await state.update_data(check_in=check_in, when_bucket=value)
    await state.set_state(SearchState.choosing_budget)
    await query.message.edit_text(
        "*Який бюджет на людину\\?* 💰",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=budget_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("b:"), SearchState.choosing_budget)
async def cb_budget(query: CallbackQuery, state: FSMContext) -> None:
    value = query.data.split(":", 1)[1] if query.data else ""
    if value == "back":
        await state.set_state(SearchState.choosing_when)
        await query.message.edit_text(
            "*Коли заїзд\\?* 📅",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=when_kb(),
        )
        await query.answer()
        return

    if value == "any":
        price_max: int | None = None
    elif value == "premium":
        price_max = None
    else:
        price_max = int(value)
    await state.update_data(price_max=price_max, budget_bucket=value)
    await state.set_state(SearchState.choosing_meal)
    await query.message.edit_text(
        "*Тип харчування\\?* 🍽",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=meal_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("m:"), SearchState.choosing_meal)
async def cb_meal(query: CallbackQuery, state: FSMContext) -> None:
    value = query.data.split(":", 1)[1] if query.data else ""
    if value == "back":
        await state.set_state(SearchState.choosing_budget)
        await query.message.edit_text(
            "*Який бюджет на людину\\?* 💰",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=budget_kb(),
        )
        await query.answer()
        return

    meal_plan = None if value == "any" else value
    await state.update_data(meal_plan=meal_plan)
    await state.set_state(SearchState.choosing_stars)
    await query.message.edit_text(
        "*Категорія готелю\\?* ⭐",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=stars_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("s:"), SearchState.choosing_stars)
async def cb_stars(query: CallbackQuery, state: FSMContext) -> None:
    value = query.data.split(":", 1)[1] if query.data else ""
    if value == "back":
        await state.set_state(SearchState.choosing_meal)
        await query.message.edit_text(
            "*Тип харчування\\?* 🍽",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=meal_kb(),
        )
        await query.answer()
        return

    stars_min = None if value == "any" else int(value)
    await state.update_data(stars_min=stars_min)
    await state.set_state(SearchState.viewing_results)
    await _show_results(query, state, edit=True)


async def _fetch_results(data: dict[str, Any]) -> dict[str, Any]:
    """Call /api/search with the FSM-stored filters. Limit pulled = 60
    (12 pages × 5 cards) so most users never trigger a refetch."""
    params: dict[str, Any] = {
        "country": data.get("country"),
        "nights": data.get("nights"),
        "check_in": data.get("check_in"),
        "price_max": data.get("price_max"),
        "meal_plan": data.get("meal_plan"),
        "stars_min": data.get("stars_min"),
        "limit": 60,
        "offset": 0,
    }
    return await search_hotels(**params)


async def _show_results(
    query: CallbackQuery,
    state: FSMContext,
    *,
    edit: bool,
    page_override: int | None = None,
) -> None:
    data = await state.get_data()
    cached = data.get(_RESULTS_KEY)
    if not cached:
        try:
            payload = await _fetch_results(data)
        except ApiError:
            await query.message.answer(
                "Сервіс пошуку тимчасово недоступний\\. Спробуйте знову через хвилину\\.",
                reply_markup=main_menu_kb(),
            )
            await query.answer()
            return
        cached = payload
        await state.update_data({_RESULTS_KEY: cached, _PAGE_KEY: 1})

    items: list[dict[str, Any]] = cached.get("items", [])
    total = cached.get("total", len(items))

    if not items:
        await query.message.edit_text(
            "Нічого не знайдено за цими фільтрами\\. Спробуйте інші параметри\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=results_actions_kb(
                has_prev=False,
                has_next=False,
                page=1,
                total_pages=1,
                subscription_set=False,
            ),
        )
        await query.answer()
        return

    page = page_override if page_override is not None else data.get(_PAGE_KEY, 1)
    total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    await state.update_data({_PAGE_KEY: page})

    start = (page - 1) * _PAGE_SIZE
    chunk = items[start : start + _PAGE_SIZE]

    header = _format_results_header(total=int(total), page=int(page), total_pages=int(total_pages))
    body = "\n\n— · — · —\n\n".join(render_search_hit(h) for h in chunk)
    text = f"{header}\n\n{body}"

    combined = _results_markup(
        chunk=chunk,
        has_prev=page > 1,
        has_next=page < total_pages,
        page=page,
        total_pages=total_pages,
        subscribed=bool(data.get("subscribed", False)),
    )

    if edit:
        try:
            await query.message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=combined,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("results.edit_skip", error=str(exc))
    else:
        await query.message.answer(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=combined,
        )
    await query.answer()


@router.callback_query(F.data == "res:prev", SearchState.viewing_results)
async def cb_prev(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await _show_results(query, state, edit=True, page_override=data.get(_PAGE_KEY, 1) - 1)


@router.callback_query(F.data == "res:next", SearchState.viewing_results)
async def cb_next(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await _show_results(query, state, edit=True, page_override=data.get(_PAGE_KEY, 1) + 1)


@router.callback_query(F.data == "res:restart", SearchState.viewing_results)
async def cb_restart(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Новий пошук…")
    await start_wizard(query.message, state)


@router.callback_query(F.data == "res:noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()


def _results_markup(
    *,
    chunk: list[dict[str, Any]],
    has_prev: bool,
    has_next: bool,
    page: int,
    total_pages: int,
    subscribed: bool,
) -> InlineKeyboardMarkup:
    detail_rows = _result_link_rows(chunk)
    nav_kb = results_actions_kb(
        has_prev=has_prev,
        has_next=has_next,
        page=page,
        total_pages=total_pages,
        subscription_set=subscribed,
    )
    return InlineKeyboardMarkup(inline_keyboard=detail_rows + nav_kb.inline_keyboard)


@router.callback_query(F.data == "res:subscribe", SearchState.viewing_results)
async def cb_subscribe(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    country = data.get("country")
    if not country:
        await query.answer("Спочатку оберіть країну для підписки", show_alert=True)
        return

    chat_id = query.from_user.id
    await ensure_subscriber(chat_id, query.from_user.username)
    sub_id = await add_subscription(
        chat_id,
        country_iso2=country,
        max_price_uah=data.get("price_max"),
        min_stars=data.get("stars_min"),
        meal_plan=data.get("meal_plan"),
    )
    await state.update_data(subscribed=True)

    cached = data.get(_RESULTS_KEY) or {}
    items: list[dict[str, Any]] = cached.get("items", [])
    if items and query.message:
        total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(1, min(int(data.get(_PAGE_KEY, 1)), total_pages))
        start = (page - 1) * _PAGE_SIZE
        chunk = items[start : start + _PAGE_SIZE]
        await query.message.edit_reply_markup(
            reply_markup=_results_markup(
                chunk=chunk,
                has_prev=page > 1,
                has_next=page < total_pages,
                page=page,
                total_pages=total_pages,
                subscribed=True,
            )
        )
    await query.answer(
        f"Підписка #{sub_id} створена: країна, бюджет, зірковість і харчування",
        show_alert=True,
    )


async def _go_back_to_country(query: CallbackQuery, state: FSMContext) -> None:
    try:
        destinations = await get_destinations()
    except ApiError:
        await query.message.answer("Сервіс тимчасово недоступний\\.")
        await query.answer()
        return
    await state.set_state(SearchState.choosing_country)
    await query.message.edit_text(
        "*Куди летимо\\?* ✈️\n\nВиберіть країну\\:",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations),
    )
    await query.answer()


@router.message(SearchState.choosing_country)
@router.message(SearchState.choosing_nights)
@router.message(SearchState.choosing_when)
@router.message(SearchState.choosing_budget)
@router.message(SearchState.choosing_meal)
@router.message(SearchState.choosing_stars)
async def text_during_wizard(message: Message, state: FSMContext) -> None:
    from src.keyboards.main_menu import (
        DEALS,
        DESTINATIONS,
        HELP,
        PROFILE,
        SEARCH,
        SUBSCRIBE,
    )

    if message.text in {SEARCH, DEALS, DESTINATIONS, SUBSCRIBE, PROFILE, HELP}:
        await state.clear()
        return

    await message.answer(
        "Будь ласка, скористайтесь кнопками вище 👆 або введіть /start щоб почати спочатку\\.",
    )
