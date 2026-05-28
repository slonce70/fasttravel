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
from src.infra.callbacks import callback_int_tail, callback_message, callback_tail
from src.infra.db import (
    add_subscription,
    delete_subscription,
    ensure_subscriber,
    list_subscriptions,
)
from src.infra.logging import get_logger
from src.keyboards.countries import countries_kb, country_emoji, country_name_uk
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
            "🔔 *Підписки на варіанти*\n\n"
            "_У вас ще немає активних підписок\\._\n\n"
            "Натисніть «➕ Додати підписку», щоб отримувати персональні "
            "сповіщення про падіння цін за вашими критеріями\\."
        )
    lines = ["🔔 *Підписки на варіанти*", ""]
    for i, sub in enumerate(subs, 1):
        iso = sub["country_iso2"]
        flag = country_emoji(iso)
        name = escape_markdown_v2(country_name_uk(iso))
        budget = escape_markdown_v2(_format_budget(sub.get("max_price_uah")))
        stars = escape_markdown_v2(_format_stars(sub.get("min_stars")))
        lines.append(f"*{i}\\.* {flag} *{name}* · {budget} · {stars}")
    return "\n".join(lines)


def _subs_kb(subs: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sub in subs:
        iso = sub["country_iso2"]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"❌ {country_emoji(iso)} {country_name_uk(iso)}",
                    callback_data=f"sub:del:{sub['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Додати підписку", callback_data="sub:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Entry: /subscribe or reply-keyboard "🔔 Підписки"
# ---------------------------------------------------------------------------


async def show_subscriptions(message: Message) -> None:
    chat_id = message.from_user.id if message.from_user else None
    if chat_id is None:
        return
    await ensure_subscriber(chat_id, message.from_user.username if message.from_user else None)
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
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    try:
        destinations = await get_destinations()
    except ApiError:
        await query.answer("Сервіс недоступний", show_alert=False)
        return
    await state.set_state(SubscribeState.country)
    await message.edit_text(
        "*🔔 Нова підписка*\n\nКраїна\\?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=countries_kb(destinations, callback_prefix="subc"),
    )
    await query.answer()


@router.callback_query(F.data.startswith("subc:"), SubscribeState.country)
async def cb_country(query: CallbackQuery, state: FSMContext) -> None:
    iso = callback_tail(query.data, "subc:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if iso == "cancel":
        await state.clear()
        await message.edit_text("Скасовано\\.")
        await query.answer()
        return
    name = country_name_uk(iso)
    await state.update_data(country=iso, country_name=name)
    await state.set_state(SubscribeState.budget)

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
    await message.edit_text(
        f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · максимальний бюджет\\? 💰",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("subb:"), SubscribeState.budget)
async def cb_budget(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "subb:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        try:
            destinations = await get_destinations()
        except ApiError:
            await query.answer("Сервіс недоступний")
            return
        await state.set_state(SubscribeState.country)
        await message.edit_text(
            "*🔔 Нова підписка*\n\nКраїна\\?",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=countries_kb(destinations, callback_prefix="subc"),
        )
        await query.answer()
        return

    max_price = None if value == "any" else callback_int_tail(query.data, "subb:")
    if value != "any" and max_price is None:
        await query.answer()
        return
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
    await message.edit_text(
        "*Мінімальна зірковість\\?* ⭐",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("subs:"), SubscribeState.stars)
async def cb_stars(query: CallbackQuery, state: FSMContext) -> None:
    value = callback_tail(query.data, "subs:") or ""
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    if value == "back":
        data = await state.get_data()
        iso = data.get("country", "")
        name = data.get("country_name") or country_name_uk(iso)
        await state.set_state(SubscribeState.budget)
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
        await message.edit_text(
            f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · максимальний бюджет\\? 💰",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb,
        )
        await query.answer()
        return

    min_stars = None if value == "any" else callback_int_tail(query.data, "subs:")
    if value != "any" and min_stars is None:
        await query.answer()
        return
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
    await message.edit_text(
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
    sub_id = callback_int_tail(query.data, "sub:del:")
    if sub_id is None:
        await query.answer()
        return
    chat_id = query.from_user.id
    ok = await delete_subscription(chat_id, sub_id)
    if ok:
        subs = await list_subscriptions(chat_id)
        message = callback_message(query)
        if message is not None:
            await message.edit_text(
                _render_subscriptions(subs),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_subs_kb(subs),
            )
        await query.answer("Підписку видалено")
    else:
        await query.answer("Не знайдено")
