"""User-facing commands: /start, /help, /channel.

Welcome flow is funnel-tight on purpose. The bot is not a search UI yet;
its only short-term job is to take a curious user from "I clicked the
link in a deal post" to "I'm subscribed to @fasttravel_deals_ua and I've
seen the website link". Anything more elaborate (saved searches, custom
filters) belongs in a follow-up phase once we have evidence the funnel
works.

Messages use MarkdownV2 since `shared.publishers.broadcast` already uses
that mode for the channel posts. Consistency keeps the escape rules in
one head.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from shared.publishers.broadcast import escape_markdown_v2
from src.config import get_settings

router = Router(name="commands")


def _channel_keyboard() -> InlineKeyboardMarkup:
    """Inline button linking to the public broadcast channel."""
    settings = get_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📡 Канал з гарячими знижками",
                    url=settings.public_channel_link,
                ),
                InlineKeyboardButton(
                    text="🌐 fasttravel.com.ua",
                    url="https://fasttravel.com.ua",
                ),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = escape_markdown_v2(message.from_user.first_name if message.from_user else "")
    body = (
        f"Привіт{', ' + name if name else ''}\\! 👋\n\n"
        "FastTravel шукає аномально низькі ціни на тури в "
        "Туреччину, Єгипет, ОАЕ, Грецію та інші напрямки\\.\n\n"
        "Підписуйся на канал нижче — кожен день до 30 пропозицій "
        "із знижкою 25%\\+ від звичайної ціни\\."
    )
    await message.answer(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_channel_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    body = (
        "Команди:\n"
        "• /start — головне меню\n"
        "• /channel — посилання на канал зі знижками\n"
        "• /help — це повідомлення\n\n"
        "Сайт із календарем цін: https://fasttravel\\.com\\.ua\n"
        "Питання, відгуки: hello@fasttravel\\.com\\.ua"
    )
    await message.answer(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


@router.message(Command("channel"))
async def cmd_channel(message: Message) -> None:
    await message.answer(
        "Канал з гарячими знижками:",
        reply_markup=_channel_keyboard(),
        disable_web_page_preview=True,
    )
