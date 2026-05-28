"""Helpers for aiogram callback handlers."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message


def callback_message(query: CallbackQuery) -> Message | None:
    """Return the editable callback message, if Telegram still exposes it."""
    message = query.message
    return message if isinstance(message, Message) else None


def callback_tail(data: str | None, prefix: str) -> str | None:
    """Return the non-empty callback suffix after ``prefix``."""
    if not data or not data.startswith(prefix):
        return None
    tail = data.removeprefix(prefix)
    return tail or None


def callback_int_tail(data: str | None, prefix: str) -> int | None:
    """Parse a decimal integer suffix from callback data."""
    tail = callback_tail(data, prefix)
    if tail is None or not tail.isdecimal():
        return None
    return int(tail)
