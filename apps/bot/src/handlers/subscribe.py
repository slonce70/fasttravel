"""/subscribe — add a price-drop alert + manage existing ones.

3-step wizard (country → budget → stars) writes a row into
`telegram_subscriber_filters`. /subscribe with no FSM context lists
existing rows + an "Add subscription" button.

The notify_subscribers scheduler job (Stage D2) reads this table on
every detect_deals tick and DMs matching deals one-by-one.
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
from src.infra.api_client import ApiError, get_destinations
from src.infra.db import (
    add_subscription,
    delete_subscription,
    ensure_subscriber,
    list_subscriptions,
)
from src.infra.logging import get_logger
from src.keyboards.countries import countries_kb, country_emoji
from src.states.subscribe import SubscribeState

router = Router(name="subscribe")
log = get_logger(__name__)


def _format_budget(value: int | None) -> str:
    if value is None:
        return "будь-яка ціна"
    return f"до {value:,} ₴".replace(",", " ")


def _format_stars(value: int | None) -> str:
    if not value:
        return "будь-яка зірковість"
    return f"{value}⭐+"


def _render_subscriptions(subs: list[dict[str, Any]]) -> str:
    if not subs:
        return (
            "🔔 *Підписки на знижки*\n\n"
            "_У вас ще немає активних підписок\\._\n\n"
            "Натисніть «➕ Додати підписку», щоб отримувати персональні "
            "сповіщення про падіння цін за вашими критеріями\\."
        )
    lines = ["🔔 *Підписки на знижки*", ""]
    for i, sub in enumerate(subs, 1):
        flag = country_emoji(sub["country_iso2"])
        budget = escape_markdown_v2(_format_budget(sub.get("max_price_uah")))
        stars = escape_markdown_v2(_format_stars(sub.get("min_stars")))
        lines.append(f"*{i}\\.* {flag} _{sub['country_iso2']}_ · {budget} · {stars}")
    return "\n".join(lines)


def _subs_kb(subs: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sub in subs:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Видалити {country_emoji(sub['country_iso2'])} {sub['country_iso2']}",
                    callback_data=f"sub:del:{sub['id']}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Додати підписку", callback_data="sub:add")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Entry: /subscribe or reply-keyboard "🔔 Підписки"
# ---------------------------------------------------------------------------


async def show_subscriptions(message: Message) -> None:
    chat_id = message.from_user.id if message.from_user else None
    if chat_id is None:
        return
    await ensure_subscriber(
        chat_id, message.from_user.username if message.from_user else None
    )
    subs = await list_subscriptions(chat_id)
    await message.answer(
        _render_subscriptions(subs),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_subs_kb(subs),
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await show_subscriptions(message)


# ---------------------------------------------------------------------------
# Add wizard
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "sub:add")
async def cb_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        destinations = await get_destinations()
    except ApiError:
        await query.answer("Сервіс недоступний", show_alert=False)
        return
    await state.set_state(SubscribeState.country)
    await query.message.edit_text(
        "*🔔 Нова підписка*\n\nКраїна\\?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations, callback_prefix="subc"),
    )
    await query.answer()


@router.callback_query(F.data.startswith("subc:"), SubscribeState.country)
async def cb_country(query: CallbackQuery, state: FSMContext) -> None:
    iso = (query.data or "").split(":", 1)[1]
    if iso == "cancel":
        await state.clear()
        await query.message.edit_text("Скасовано\\.")
        await query.answer()
        return
    await state.update_data(country=iso)
    await state.set_state(SubscribeState.budget)

    # Budget keyboard tailored for subscription — same brackets as wizard
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="до 30 000 ₴", callback_data="subb:30000"),
                InlineKeyboardButton(text="до 50 000 ₴", callback_data="subb:50000"),
            ],
            [
                InlineKeyboardButton(text="до 80 000 ₴", callback_data="subb:80000"),
                InlineKeyboardButton(text="до 120 000 ₴", callback_data="subb:120000"),
            ],
            [InlineKeyboardButton(text="Будь-яка ціна", callback_data="subb:any")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="subb:back")],
        ]
    )
    await query.message.edit_text(
        f"{country_emoji(iso)} _{iso}_ · *максимальний бюджет\\?* 💰",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("subb:"), SubscribeState.budget)
async def cb_budget(query: CallbackQuery, state: FSMContext) -> None:
    value = (query.data or "").split(":", 1)[1]
    if value == "back":
        try:
            destinations = await get_destinations()
        except ApiError:
            await query.answer("Сервіс недоступний")
            return
        await state.set_state(SubscribeState.country)
        await query.message.edit_text(
            "*🔔 Нова підписка*\n\nКраїна\\?",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=countries_kb(destinations, callback_prefix="subc"),
        )
        await query.answer()
        return

    max_price: int | None = None if value == "any" else int(value)
    await state.update_data(max_price_uah=max_price)
    await state.set_state(SubscribeState.stars)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3⭐+", callback_data="subs:3"),
                InlineKeyboardButton(text="4⭐+", callback_data="subs:4"),
                InlineKeyboardButton(text="5⭐", callback_data="subs:5"),
            ],
            [InlineKeyboardButton(text="🤷 Будь-яка", callback_data="subs:any")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="subs:back")],
        ]
    )
    await query.message.edit_text(
        "*Мінімальна зірковість\\?* ⭐",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("subs:"), SubscribeState.stars)
async def cb_stars(query: CallbackQuery, state: FSMContext) -> None:
    value = (query.data or "").split(":", 1)[1]
    if value == "back":
        data = await state.get_data()
        iso = data.get("country", "")
        # Reuse the budget keyboard from cb_country path
        await state.set_state(SubscribeState.budget)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="до 30 000 ₴", callback_data="subb:30000"
                    ),
                    InlineKeyboardButton(
                        text="до 50 000 ₴", callback_data="subb:50000"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="до 80 000 ₴", callback_data="subb:80000"
                    ),
                    InlineKeyboardButton(
                        text="до 120 000 ₴", callback_data="subb:120000"
                    ),
                ],
                [InlineKeyboardButton(text="Будь-яка ціна", callback_data="subb:any")],
                [InlineKeyboardButton(text="◀ Назад", callback_data="subb:back")],
            ]
        )
        await query.message.edit_text(
            f"{country_emoji(iso)} _{iso}_ · *максимальний бюджет\\?* 💰",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb,
        )
        await query.answer()
        return

    min_stars: int | None = None if value == "any" else int(value)
    data = await state.get_data()
    chat_id = query.from_user.id

    await ensure_subscriber(chat_id, query.from_user.username)
    sub_id = await add_subscription(
        chat_id,
        country_iso2=data["country"],
        max_price_uah=data.get("max_price_uah"),
        min_stars=min_stars,
        meal_plan=None,
    )
    await state.clear()

    subs = await list_subscriptions(chat_id)
    await query.message.edit_text(
        "✅ *Підписку створено\\!*\n\n"
        "Ми надішлемо вам особисте повідомлення, коли знайдемо тур, що "
        "відповідає цим критеріям \\(і не настирливі сповіщення\\)\\.\n\n"
        + _render_subscriptions(subs),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_subs_kb(subs),
    )
    await query.answer(f"Підписка #{sub_id} створена")


# ---------------------------------------------------------------------------
# Delete a single subscription
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("sub:del:"))
async def cb_delete(query: CallbackQuery) -> None:
    try:
        sub_id = int((query.data or "").split(":", 2)[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    chat_id = query.from_user.id
    ok = await delete_subscription(chat_id, sub_id)
    if ok:
        subs = await list_subscriptions(chat_id)
        await query.message.edit_text(
            _render_subscriptions(subs),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_subs_kb(subs),
        )
        await query.answer("Підписку видалено")
    else:
        await query.answer("Не знайдено")
