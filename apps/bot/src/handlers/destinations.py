"""Destinations handler — STUB (Stage A). Replaced in Stage C."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="destinations")


async def show_destinations(message: Message) -> None:
    await message.answer("🌍 Каталог напрямків — модуль готується\\.")


@router.message(Command("destinations"))
async def cmd_destinations(message: Message) -> None:
    await show_destinations(message)
