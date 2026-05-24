"""Profile handler — STUB (Stage A). Replaced in Stage D."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="profile")


async def show_profile(message: Message) -> None:
    await message.answer("👤 Профіль — модуль готується\\.")


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await show_profile(message)
