"""/profile — user-facing dashboard: subscriptions + GDPR delete button.

Read-only listing of telegram_subscribers + filters. The only mutating
action is "Видалити всі дані" — and that hits a confirmation step so
users can't fat-finger their way to data loss.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    get_pause_state,
    list_subscriptions,
    maybe_auto_resume,
    pause_all_alerts,
    resume_all_alerts,
)

router = Router(name="profile")


def _profile_kb() -> InlineKeyboardMarkup:
    """Account hub — every button is a working entrypoint (no dead ends).

    «Канал» reuses the public channel link from settings (same target as
    the /channel command); «⏸ Сповіщення» opens the notifications submenu
    (global pause / resume).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Мої підписки", callback_data="prof:subs")],
            [InlineKeyboardButton(text="⏸ Сповіщення", callback_data="prof:notif")],
            [InlineKeyboardButton(text="📡 Канал", url=get_settings().public_channel_link)],
            [InlineKeyboardButton(text="🗑 Видалити всі дані", callback_data="prof:delete")],
        ]
    )


def _notif_state_line(pause: dict[str, object] | None) -> str:
    """One MarkdownV2-escaped status line describing the global-pause state."""
    if pause is None:
        return "🔔 Сповіщення: *увімкнені*"
    until_iso = pause.get("until")
    if isinstance(until_iso, str):
        try:
            until = datetime.fromisoformat(until_iso)
        except ValueError:
            until = None
        if until is not None:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            until_txt = escape_markdown_v2(format_date_short(until))
            return f"⏸ На паузі до *{until_txt}*"
    return "⏸ На паузі *поки не ввімкнете*"


def _notif_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏸ Пауза 24 год", callback_data="prof:pause:24h")],
            [InlineKeyboardButton(text="⏸ Пауза 7 днів", callback_data="prof:pause:7d")],
            [InlineKeyboardButton(text="⏸ Поки не ввімкну", callback_data="prof:pause:forever")],
            [InlineKeyboardButton(text="▶ Відновити", callback_data="prof:resume")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="prof:back")],
        ]
    )


def _render_notif(pause: dict[str, object] | None) -> str:
    return (
        "⏸ *Сповіщення*\n\n"
        f"{_notif_state_line(pause)}\n\n"
        "_Пауза зупиняє ВСІ персональні алерти\\. Таймер спрацьовує під час "
        "наступної взаємодії, тож пауза триває щонайменше вказаний час\\._"
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
    # Lazy expiry — a timed pause that has elapsed is resumed on interaction.
    await maybe_auto_resume(user.id)
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


# ---------------------------------------------------------------------------
# Notifications submenu — global pause / resume.
#
# Pause/resume flip `telegram_subscriber_filters.is_active` in bulk; the
# notify scheduler already filters `WHERE f.is_active`, so this is the whole
# enforcement. State (which subs we paused + the expiry) lives in
# telegram_subscribers.filters_jsonb under a "pause" key.
# ---------------------------------------------------------------------------


async def _show_notif(message: Message, chat_id: int) -> None:
    pause = await get_pause_state(chat_id)
    await message.edit_text(
        _render_notif(pause),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_notif_kb(),
    )


@router.callback_query(F.data == "prof:notif")
async def cb_notif(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    # Lazy expiry — expire a timed pause when the user opens this menu.
    await maybe_auto_resume(query.from_user.id)
    await _show_notif(message, query.from_user.id)
    await query.answer()


@router.callback_query(F.data == "prof:back")
async def cb_notif_back(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await maybe_auto_resume(query.from_user.id)
    subs = await list_subscriptions(query.from_user.id)
    name = escape_markdown_v2(query.from_user.first_name or "")
    greeting = f"👤 *Профіль* {name}".rstrip()
    lines = [
        greeting,
        "",
        f"🆔 ID: `{query.from_user.id}`",
        f"🔔 Активних підписок: *{len(subs)}*",
        "",
        "_Натисніть «Мої підписки» нижче, щоб переглянути / видалити_\\.",
    ]
    await message.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_profile_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("prof:pause:"))
async def cb_pause(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    span = (query.data or "").removeprefix("prof:pause:")
    now = datetime.now(timezone.utc)
    if span == "24h":
        until: datetime | None = now + timedelta(hours=24)
        toast = "Пауза на 24 год"
    elif span == "7d":
        until = now + timedelta(days=7)
        toast = "Пауза на 7 днів"
    elif span == "forever":
        until = None
        toast = "Пауза до ввімкнення"
    else:
        await query.answer()
        return
    await pause_all_alerts(query.from_user.id, until)
    await _show_notif(message, query.from_user.id)
    await query.answer(toast)


@router.callback_query(F.data == "prof:resume")
async def cb_resume(query: CallbackQuery) -> None:
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    count = await resume_all_alerts(query.from_user.id)
    await _show_notif(message, query.from_user.id)
    await query.answer(f"Відновлено: {count}" if count else "Сповіщення увімкнені")


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
