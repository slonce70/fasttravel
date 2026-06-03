"""Search wizard: hotel name → country → nights → when → budget → meal → stars → results.

State machine lives in `src.states.search.SearchState`. Each step renders
its keyboard, accepts a callback, persists the choice via `state.update_data`,
and advances to the next state. Results page calls `/api/search` once and
paginates through the cached list.

Cancellation: `hq:cancel`, `cc:cancel`, or `/start` clears FSM + sends the
user back to the main menu.
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
    Message,
)

from shared.publishers.broadcast import escape_markdown_v2
from src.config import get_settings
from src.handlers.wizard_render import format_results_header, results_markup, step_prefix
from src.infra.api_client import ApiError, get_destinations, search_hotels
from src.infra.callbacks import callback_int_tail, callback_message, callback_tail
from src.infra.db import add_subscription, ensure_subscriber, find_subscription
from src.infra.logging import get_logger
from src.keyboards.countries import countries_kb, country_emoji, country_name_uk
from src.keyboards.filters import (
    budget_kb,
    hotel_query_kb,
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
_MIN_HOTEL_QUERY_LEN = 2


async def start_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchState.choosing_hotel_query)
    await message.answer(
        f"{step_prefix('hotel')}*Шукаєте конкретний готель\\?* 🔎\n\n"
        "Введіть частину назви \\(наприклад, `Rixos` або `Dana Beach`\\) "
        "або пропустіть цей крок\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=hotel_query_kb(),
    )


async def _show_country_choice(message: Message, state: FSMContext, *, edit: bool) -> None:
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
    text = f"{step_prefix('country')}*Куди летимо\\?* ✈️\n\nВиберіть країну\\:"
    if edit:
        await message.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=countries_kb(destinations),
        )
        return
    await message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations),
    )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    await start_wizard(message, state)


@router.callback_query(F.data.startswith("hq:"), SearchState.choosing_hotel_query)
async def cb_hotel_query_choice(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "hq:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "cancel":
        await state.clear()
        await message.edit_text("Пошук скасовано\\.")
        await query.answer()
        return
    if value != "skip":
        await query.answer()
        return
    await state.update_data(q=None)
    await _show_country_choice(message, state, edit=True)
    await query.answer()


@router.message(SearchState.choosing_hotel_query)
async def text_hotel_query(message: Message, state: FSMContext) -> None:
    query = " ".join((message.text or "").strip().split())
    if len(query) < _MIN_HOTEL_QUERY_LEN:
        await message.answer(
            "Введіть хоча б 2 символи назви готелю або натисніть «Пропустити назву»\\.",
            reply_markup=hotel_query_kb(),
        )
        return
    await state.update_data(q=query[:80], country=None, country_name=None, country_emoji=None)
    await state.set_state(SearchState.choosing_nights)
    await message.answer(
        f"{step_prefix('nights')}*Готель:* {escape_markdown_v2(query[:80])}\n\n"
        "*Скільки ночей\\?* 🌙",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=nights_kb(),
    )


@router.callback_query(F.data.startswith("cc:"), SearchState.choosing_country)
async def cb_country(query: CallbackQuery, state: FSMContext) -> None:
    iso = callback_tail(query.data, "cc:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if iso == "cancel":
        await state.clear()
        await message.edit_text("Пошук скасовано\\.")
        await query.answer()
        return

    name = country_name_uk(iso)
    await state.update_data(country=iso, country_emoji=country_emoji(iso), country_name=name)
    await state.set_state(SearchState.choosing_nights)
    await message.edit_text(
        f"{step_prefix('nights')}{country_emoji(iso)} "
        f"*{escape_markdown_v2(name)}* · скільки ночей\\? 🌙",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=nights_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("n:"), SearchState.choosing_nights)
async def cb_nights(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "n:") or ""
    if value == "back":
        data = await state.get_data()
        if data.get("q"):
            await _go_back_to_hotel_query(query, state)
        else:
            await _go_back_to_country(query, state)
        return
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    nights = None if value == "any" else callback_int_tail(query.data, "n:")
    if value != "any" and nights is None:
        await query.answer()
        return
    await state.update_data(nights=nights)
    await state.set_state(SearchState.choosing_when)
    await message.edit_text(
        f"{step_prefix('when')}*Коли заїзд\\?* 📅",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=when_kb(),
    )
    await query.answer()


# Each "when" bucket is a *range* of check-in days from today, not a single
# pinned day. The labels promise a window («Найближчі тижні», «Через місяць»,
# «Через 2-3 місяці»), so we send check_in_min/check_in_max and let the API
# match any departure inside it. Pinning one exact day (the old behaviour)
# matched almost nothing because a hotel rarely has a snapshot on that precise
# date. Bounds are inclusive, expressed as (floor_days, ceiling_days) offsets
# from today; ``None`` means «Без різниці» — no date filter at all.
_WHEN_RANGES_DAYS: dict[str, tuple[int, int] | None] = {
    "soon": (0, 21),
    "month": (22, 45),
    "season": (46, 90),
    "any": None,
}


def when_bucket_range(value: str, *, today: date | None = None) -> tuple[str, str] | None:
    """Map a "when" bucket to an inclusive (check_in_min, check_in_max) ISO
    date pair, or ``None`` for the no-filter «Без різниці» bucket / unknown
    values. Pure + testable (``today`` injectable)."""
    span = _WHEN_RANGES_DAYS.get(value)
    if span is None:
        return None
    base = today or date.today()
    floor_days, ceiling_days = span
    return (
        (base + timedelta(days=floor_days)).isoformat(),
        (base + timedelta(days=ceiling_days)).isoformat(),
    )


@router.callback_query(F.data.startswith("w:"), SearchState.choosing_when)
async def cb_when(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "w:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        await state.set_state(SearchState.choosing_nights)
        await message.edit_text(
            f"{step_prefix('nights')}*Скільки ночей\\?* 🌙",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=nights_kb(),
        )
        await query.answer()
        return

    date_range = when_bucket_range(value)
    check_in_min = date_range[0] if date_range else None
    check_in_max = date_range[1] if date_range else None
    await state.update_data(
        check_in_min=check_in_min,
        check_in_max=check_in_max,
        when_bucket=value,
    )
    await state.set_state(SearchState.choosing_budget)
    await message.edit_text(
        f"{step_prefix('budget')}*Який бюджет на людину\\?* 💰",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=budget_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("b:"), SearchState.choosing_budget)
async def cb_budget(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "b:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        await state.set_state(SearchState.choosing_when)
        await message.edit_text(
            f"{step_prefix('when')}*Коли заїзд\\?* 📅",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=when_kb(),
        )
        await query.answer()
        return

    # Budget buttons set a price CEILING (``price_max``). «Без обмежень»
    # (``any``) sends no ceiling; every other button caps at its value.
    # There is no «Преміум»/floor option because the API cannot express a
    # price minimum — it would just repeat the unfiltered «any» query.
    if value == "any":
        price_max: int | None = None
    else:
        price_max = callback_int_tail(query.data, "b:")
        if price_max is None:
            await query.answer()
            return
    await state.update_data(price_max=price_max, budget_bucket=value)
    await state.set_state(SearchState.choosing_meal)
    await message.edit_text(
        f"{step_prefix('meal')}*Тип харчування\\?* 🍽",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=meal_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("m:"), SearchState.choosing_meal)
async def cb_meal(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "m:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        await state.set_state(SearchState.choosing_budget)
        await message.edit_text(
            f"{step_prefix('budget')}*Який бюджет на людину\\?* 💰",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=budget_kb(),
        )
        await query.answer()
        return

    meal_plan = None if value == "any" else value
    await state.update_data(meal_plan=meal_plan)
    await state.set_state(SearchState.choosing_stars)
    await message.edit_text(
        f"{step_prefix('stars')}*Категорія готелю\\?* ⭐",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=stars_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("s:"), SearchState.choosing_stars)
async def cb_stars(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "s:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        await state.set_state(SearchState.choosing_meal)
        await message.edit_text(
            f"{step_prefix('meal')}*Тип харчування\\?* 🍽",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=meal_kb(),
        )
        await query.answer()
        return

    stars_min = None if value == "any" else callback_int_tail(query.data, "s:")
    if value != "any" and stars_min is None:
        await query.answer()
        return
    await state.update_data(stars_min=stars_min)
    await state.set_state(SearchState.viewing_results)
    await _show_results(query, state, edit=True)


async def _fetch_results(data: dict[str, Any]) -> dict[str, Any]:
    """Call /api/search with the FSM-stored filters. Limit pulled = 60
    (12 pages × 5 cards) so most users never trigger a refetch."""
    params: dict[str, Any] = {
        "q": data.get("q"),
        "country": data.get("country"),
        "nights": data.get("nights"),
        # Range semantics: the "when" bucket stores a floor + ceiling so the
        # API matches any departure inside the advertised window. None values
        # are stripped by the api_client (no date filter for «Без різниці»).
        "check_in_min": data.get("check_in_min"),
        "check_in_max": data.get("check_in_max"),
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
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    data = await state.get_data()
    cached = data.get(_RESULTS_KEY)
    if not cached:
        try:
            payload = await _fetch_results(data)
        except ApiError:
            await message.answer(
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
        await message.edit_text(
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

    header = format_results_header(
        total=int(total),
        page=int(page),
        total_pages=int(total_pages),
        shown=len(items),
    )
    body = "\n\n— · — · —\n\n".join(render_search_hit(h) for h in chunk)
    text = f"{header}\n\n{body}"

    combined = results_markup(
        chunk=chunk,
        has_prev=page > 1,
        has_next=page < total_pages,
        page=page,
        total_pages=total_pages,
        subscribed=bool(data.get("subscribed", False)),
        site_base_url=get_settings().public_site_url,
    )

    if edit:
        try:
            await message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=combined,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("results.edit_skip", error=str(exc))
    else:
        await message.answer(
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
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await query.answer("Новий пошук…")
    await start_wizard(message, state)


@router.callback_query(F.data == "res:noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()


@router.callback_query(F.data == "res:subscribe", SearchState.viewing_results)
async def cb_subscribe(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    country = data.get("country")
    if not country:
        await query.answer("Спочатку оберіть країну для підписки", show_alert=True)
        return

    chat_id = query.from_user.id
    max_price = data.get("price_max")
    min_stars = data.get("stars_min")
    meal_plan = data.get("meal_plan")
    await ensure_subscriber(chat_id, query.from_user.username)
    # Conservative dedup: if the user already has a subscription with this
    # exact natural key, reuse it instead of piling up an identical row that
    # would double the alert DMs for the same deal.
    existing_id = await find_subscription(
        chat_id,
        country_iso2=country,
        max_price_uah=max_price,
        min_stars=min_stars,
        meal_plan=meal_plan,
    )
    is_duplicate = existing_id is not None
    if existing_id is not None:
        sub_id = existing_id
    else:
        sub_id = await add_subscription(
            chat_id,
            country_iso2=country,
            max_price_uah=max_price,
            min_stars=min_stars,
            meal_plan=meal_plan,
        )
    await state.update_data(subscribed=True)

    cached = data.get(_RESULTS_KEY) or {}
    items: list[dict[str, Any]] = cached.get("items", [])
    message = callback_message(query)
    if items and message is not None:
        total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(1, min(int(data.get(_PAGE_KEY, 1)), total_pages))
        start = (page - 1) * _PAGE_SIZE
        chunk = items[start : start + _PAGE_SIZE]
        await message.edit_reply_markup(
            reply_markup=results_markup(
                chunk=chunk,
                has_prev=page > 1,
                has_next=page < total_pages,
                page=page,
                total_pages=total_pages,
                subscribed=True,
                site_base_url=get_settings().public_site_url,
            )
        )
    if is_duplicate:
        await query.answer(
            "Ви вже маєте таку підписку — нову не створювали",
            show_alert=True,
        )
    else:
        await query.answer(
            f"Підписка #{sub_id} створена: країна, бюджет, зірковість і харчування",
            show_alert=True,
        )


async def _go_back_to_country(query: CallbackQuery, state: FSMContext) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    try:
        destinations = await get_destinations()
    except ApiError:
        await message.answer("Сервіс тимчасово недоступний\\.")
        await query.answer()
        return
    await state.set_state(SearchState.choosing_country)
    await message.edit_text(
        f"{step_prefix('country')}*Куди летимо\\?* ✈️\n\nВиберіть країну\\:",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations),
    )
    await query.answer()


async def _go_back_to_hotel_query(query: CallbackQuery, state: FSMContext) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await state.set_state(SearchState.choosing_hotel_query)
    await message.edit_text(
        f"{step_prefix('hotel')}*Шукаєте конкретний готель\\?* 🔎\n\n"
        "Введіть частину назви або пропустіть цей крок\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=hotel_query_kb(),
    )
    await query.answer()


@router.message(SearchState.choosing_country)
@router.message(SearchState.choosing_nights)
@router.message(SearchState.choosing_when)
@router.message(SearchState.choosing_budget)
@router.message(SearchState.choosing_meal)
@router.message(SearchState.choosing_stars)
async def text_during_wizard(message: Message) -> None:
    # Main-menu taps are intercepted by the commands router (registered
    # first) which now clears FSM state itself, so no menu-text branch is
    # needed here — any text that reaches this handler is genuine free text
    # typed mid-step. (State filtering lives in the decorators above.)
    await message.answer(
        "Будь ласка, скористайтесь кнопками вище 👆 або введіть /start щоб почати спочатку\\.",
    )


@router.message(SearchState.viewing_results)
async def text_during_results(message: Message) -> None:
    # On the results page the only controls are inline buttons (pagination +
    # «Новий пошук»). Free text here previously matched no handler and the
    # bot stayed silent, which reads as broken; point the user at the buttons.
    await message.answer(
        "Гортайте результати кнопками ◀ ▶ нижче або натисніть «🔄 Новий пошук»\\. "
        "Для нового запиту введіть /search\\.",
    )
