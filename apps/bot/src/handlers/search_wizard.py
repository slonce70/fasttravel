"""Search wizard — STUB (Stage A). Replaced in Stage B."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name="search_wizard")


async def start_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔍 Майстер пошуку — модуль готується\\.")


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    await start_wizard(message, state)
