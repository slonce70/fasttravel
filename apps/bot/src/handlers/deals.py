"""Deals handler — STUB (Stage A). Replaced in Stage C."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="deals")


async def show_deals(message: Message) -> None:
    """Entrypoint used both by the /deals command and the reply-keyboard
    text dispatcher (commands.text_deals)."""
    await message.answer("🔥 Гарячі знижки — модуль готується\\.")


@router.message(Command("deals"))
async def cmd_deals(message: Message) -> None:
    await show_deals(message)
