"""Subscriptions handler — STUB (Stage A). Replaced in Stage D."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="subscribe")


async def show_subscriptions(message: Message) -> None:
    await message.answer("🔔 Підписки — модуль готується\\.")


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await show_subscriptions(message)
