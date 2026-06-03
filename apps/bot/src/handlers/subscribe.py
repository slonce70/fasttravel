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
    find_subscription,
    list_subscriptions,
    set_subscription_active,
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


def _budget_kb() -> InlineKeyboardMarkup:
    """Budget-step keyboard — shared by the country→budget step and the
    stars→budget back navigation."""
    return InlineKeyboardMarkup(
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
        # `is_active` defaults to True so a test/legacy dict without the key
        # never paints an active sub as paused. The suffix's parens are
        # MarkdownV2-reserved, hence escape_markdown_v2.
        paused = "" if sub.get("is_active", True) else f" {escape_markdown_v2('(на паузі)')}"
        lines.append(f"*{i}\\.* {flag} *{name}* · {budget} · {stars}{paused}")
    return "\n".join(lines)


def _subs_kb(subs: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sub in subs:
        iso = sub["country_iso2"]
        sub_id = sub["id"]
        if sub.get("is_active", True):
            toggle = InlineKeyboardButton(text="🔕 Призупинити", callback_data=f"sub:mute:{sub_id}")
        else:
            toggle = InlineKeyboardButton(text="🔔 Увімкнути", callback_data=f"sub:on:{sub_id}")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"❌ {country_emoji(iso)} {country_name_uk(iso)}",
                    callback_data=f"sub:del:{sub_id}",
                ),
                toggle,
                InlineKeyboardButton(text="✏️ Змінити", callback_data=f"sub:edit:{sub_id}"),
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

    await message.edit_text(
        f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · максимальний бюджет\\? 💰",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_budget_kb(),
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
        await message.edit_text(
            f"{country_emoji(iso)} *{escape_markdown_v2(name)}* · максимальний бюджет\\? 💰",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_budget_kb(),
        )
        await query.answer()
        return

    min_stars = None if value == "any" else callback_int_tail(query.data, "subs:")
    if value != "any" and min_stars is None:
        await query.answer()
        return
    data = await state.get_data()
    chat_id = query.from_user.id
    country_iso2 = data["country"]
    max_price_uah = data.get("max_price_uah")

    await ensure_subscriber(chat_id, query.from_user.username)
    # Conservative dedup: reuse an identical existing subscription instead of
    # piling up a duplicate row (which would double the alert DMs).
    existing_id = await find_subscription(
        chat_id,
        country_iso2=country_iso2,
        max_price_uah=max_price_uah,
        min_stars=min_stars,
        meal_plan=None,
    )
    if existing_id is not None:
        sub_id = existing_id
        is_duplicate = True
    else:
        sub_id = await add_subscription(
            chat_id,
            country_iso2=country_iso2,
            max_price_uah=max_price_uah,
            min_stars=min_stars,
            meal_plan=None,
        )
        is_duplicate = False
    await state.clear()

    subs = await list_subscriptions(chat_id)
    if is_duplicate:
        header = (
            "ℹ️ *Ви вже маєте таку підписку\\!*\n\n"
            "Нову не створювали — щоб не дублювати сповіщення\\.\n\n"
        )
        answer = "Ви вже маєте таку підписку"
    else:
        header = (
            "✅ *Підписку створено\\!*\n\n"
            "Ми надішлемо вам особисте повідомлення, коли знайдемо тур, що "
            "відповідає цим критеріям \\(і не настирливі сповіщення\\)\\.\n\n"
        )
        answer = f"Підписка #{sub_id} створена"
    await message.edit_text(
        header + _render_subscriptions(subs),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_subs_kb(subs),
    )
    await query.answer(answer)


# ---------------------------------------------------------------------------
# Edit a subscription
#
# Simplest correct approach (the spec's sanctioned fallback): delete the old
# row, then re-enter the existing add wizard. Re-seeding the wizard with the
# old values fights cb_add's state.clear() and the find_subscription dedup in
# cb_stars (editing to the SAME combo would dedup-noop instead of replacing),
# so we keep it as a clean "remove + add fresh" flow and reuse the wizard.
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("sub:edit:"))
async def cb_edit(query: CallbackQuery, state: FSMContext) -> None:
    sub_id = callback_int_tail(query.data, "sub:edit:")
    if sub_id is None:
        await query.answer()
        return
    chat_id = query.from_user.id
    await delete_subscription(chat_id, sub_id)
    # Re-enter the add wizard from the country step (reuses cb_add's flow).
    await cb_add(query, state)


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


# ---------------------------------------------------------------------------
# Per-subscription mute / un-mute (toggle is_active).
#
# `set_subscription_active` is the enforcement: the notify scheduler filters
# `WHERE f.is_active`, so a muted sub simply stops being matched. NOT state-
# bound (no SubscribeState filter), so `sub:mute:` also fires when tapped from
# a scheduler alert message — in that case the message has no sub-list to
# re-render, so we guard `message is not None` (like cb_delete) and fall back
# to a toast.
# ---------------------------------------------------------------------------


async def _toggle_subscription(query: CallbackQuery, prefix: str, active: bool, toast: str) -> None:
    sub_id = callback_int_tail(query.data, prefix)
    if sub_id is None:
        await query.answer()
        return
    chat_id = query.from_user.id
    ok = await set_subscription_active(chat_id, sub_id, active)
    if not ok:
        await query.answer("Не знайдено")
        return
    message = callback_message(query)
    if message is not None:
        subs = await list_subscriptions(chat_id)
        try:
            await message.edit_text(
                _render_subscriptions(subs),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_subs_kb(subs),
            )
        except Exception:  # noqa: BLE001
            # The originating message may not be the subs list (e.g. a
            # scheduler alert), so an edit can fail — the toast still confirms.
            pass
    await query.answer(toast)


@router.callback_query(F.data.startswith("sub:mute:"))
async def cb_mute(query: CallbackQuery) -> None:
    await _toggle_subscription(query, "sub:mute:", active=False, toast="Підписку призупинено")


@router.callback_query(F.data.startswith("sub:on:"))
async def cb_unmute(query: CallbackQuery) -> None:
    await _toggle_subscription(query, "sub:on:", active=True, toast="Підписку ввімкнено")
