"""Telegram channel publisher — shared between bot and scheduler.

Single responsibility: take an aiogram Bot + a rendered MarkdownV2 text,
push it to the channel, return the Telegram message id. Render is the
caller's job; escaping helpers live here because anyone formatting a
MarkdownV2 message needs them.

aiogram v3 surface notes:
  - `Bot(token, default=DefaultBotProperties(parse_mode=...))` is the v3
    way to set per-bot defaults. The per-call `parse_mode` arg still
    works and is more explicit, so we pass it on every send.
  - `RetryAfter` is raised when Telegram returns 429 with a `retry_after`.
    We wrap in a single retry loop with the suggested delay; persistent
    rate-limiting should surface as a job failure so APScheduler can log.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

# MarkdownV2 reserves these in body text. Any DB-supplied substring (hotel
# name, destination, operator name, dates) MUST be escaped before being
# slotted into a template. The template itself can leave its own literal
# punctuation pre-escaped — see jobs/post_deals.py.
MARKDOWN_V2_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"
_ESCAPE_TABLE = str.maketrans({ch: f"\\{ch}" for ch in MARKDOWN_V2_ESCAPE_CHARS})


def escape_markdown_v2(text: str | None) -> str:
    """Escape every MarkdownV2 reserved char in *text*.

    Returns an empty string for None/empty input so templates don't
    explode on optional fields (e.g. an unmapped destination name).
    """
    if not text:
        return ""
    return text.translate(_ESCAPE_TABLE)


def make_bot(token: str) -> Bot:
    """Construct an aiogram Bot with MarkdownV2 as the default parse mode."""
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
    """Send a deal post to *channel_id*. Returns the Telegram message id.

    Caller passes already-rendered MarkdownV2 text. `channel_id` accepts
    either the numeric `-100...` form or `@channel_slug`.

    On `TelegramRetryAfter` we sleep the suggested delay and retry once;
    further failures bubble up so APScheduler logs them and the job
    finishes early (the next 15-minute tick will try the same deals).
    """
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
