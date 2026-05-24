"""Telegram channel publisher helpers for scheduler deal broadcasts."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

MARKDOWN_V2_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"
_ESCAPE_TABLE = str.maketrans({ch: f"\\{ch}" for ch in MARKDOWN_V2_ESCAPE_CHARS})


def escape_markdown_v2(text: str | None) -> str:
    """Escape every MarkdownV2 reserved char in text."""
    if not text:
        return ""
    return text.translate(_ESCAPE_TABLE)


def make_bot(token: str) -> Bot:
    """Construct an aiogram Bot with MarkdownV2 defaults."""
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )


async def broadcast_deal(
    bot: Bot,
    channel_id: int | str,
    text: str,
    *,
    disable_web_page_preview: bool = False,
    max_retries: int = 1,
) -> int:
    """Send a deal post to channel_id and return the Telegram message id."""
    attempt = 0
    while True:
        try:
            msg = await bot.send_message(
                chat_id=channel_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=disable_web_page_preview,
            )
            return msg.message_id
        except TelegramRetryAfter as exc:
            if attempt >= max_retries:
                raise
            attempt += 1
            await asyncio.sleep(exc.retry_after)
