"""/profile — user-facing dashboard: subscriptions + GDPR delete button.

Read-only listing of telegram_subscribers + filters. The only mutating
action is "Видалити всі дані" — and that hits a confirmation step so
users can't fat-finger their way to data loss.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from shared.publishers.broadcast import escape_markdown_v2
from shared.text_uk import format_date_short
from src.config import get_settings
from src.infra.callbacks import callback_message
from src.infra.db import (
    delete_all_user_data,
    ensure_subscriber,
    get_last_notification,
    list_subscriptions,
)

router = Router(name="profile")


def _profile_kb() -> InlineKeyboardMarkup:
    """Account hub — every button is a working entrypoint (no dead ends).

    «Канал» reuses the public channel link from settings (same target as
    the /channel command); we deliberately omit a pause/notifications
    toggle here — that arrives in a later phase, so leaving it out now
    avoids a dead button.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Мої підписки", callback_data="prof:subs")],
            [InlineKeyboardButton(text="📡 Канал", url=get_settings().public_channel_link)],
            [InlineKeyboardButton(text="🗑 Видалити всі дані", callback_data="prof:delete")],
        ]
    )


def _confirm_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Так, видалити", callback_data="prof:delete:yes"),
                InlineKeyboardButton(text="Скасувати", callback_data="prof:delete:no"),
            ]
        ]
    )


async def show_profile(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await ensure_subscriber(user.id, user.username)
    subs = await list_subscriptions(user.id)
    last_alert = await get_last_notification(user.id)

    name = escape_markdown_v2(user.first_name or "")
    greeting = f"👤 *Профіль* {name}".rstrip()
    lines = [
        greeting,
        "",
        f"🆔 ID: `{user.id}`",
        f"🔔 Активних підписок: *{len(subs)}*",
    ]
    # Read-only «last alert» line — shown only when the user has actually
    # been alerted, so we never render an empty / "None" date.
    if last_alert is not None:
        last_alert_txt = escape_markdown_v2(format_date_short(last_alert))
        lines.append(f"🕓 Останній алерт: {last_alert_txt}")
    lines += [
        "",
        "_Натисніть «Мої підписки» нижче, щоб переглянути / видалити_\\.",
    ]
    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_profile_kb(),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await show_profile(message)


@router.callback_query(F.data == "prof:subs")
async def cb_subs(query: CallbackQuery) -> None:
    # Hand off to the subscribe handler so user sees the same UX
    from src.handlers.subscribe import show_subscriptions

    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await query.answer()
    await show_subscriptions(message)


@router.callback_query(F.data == "prof:delete")
async def cb_delete_confirm(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await message.edit_text(
        "🗑 *Видалити всі дані\\?*\n\nЦе безповоротно видалить ваш профіль і всі підписки\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_confirm_delete_kb(),
    )
    await query.answer()


@router.callback_query(F.data == "prof:delete:no")
async def cb_delete_no(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await message.edit_text(
        "Скасовано\\. Дані не зачіпали\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await query.answer()


@router.callback_query(F.data == "prof:delete:yes")
async def cb_delete_yes(query: CallbackQuery) -> None:
    await delete_all_user_data(query.from_user.id)
    message = callback_message(query)
    if message is not None:
        await message.edit_text(
            "✅ Всі дані видалено\\. Дякуємо, що були з нами\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    await query.answer("Готово")
