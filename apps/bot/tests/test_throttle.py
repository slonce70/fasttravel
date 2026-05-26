"""ThrottleMiddleware drops events past the per-user sliding window.

We construct a real aiogram Message so the middleware's `isinstance`
guard accepts it; everything else (time, the handler) is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram.types import Chat, Message, User
from src.infra.middleware import ThrottleMiddleware


def _make_message(uid: int) -> Message:
    """Minimal aiogram-typed Message — fields that ThrottleMiddleware
    actually reads (from_user.id) are populated; the rest matches the
    schema defaults so pydantic accepts it."""
    return Message.model_construct(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat.model_construct(id=uid, type="private"),
        from_user=User.model_construct(id=uid, is_bot=False, first_name="Test"),
        text="hi",
    )


@pytest.mark.asyncio
async def test_throttle_allows_under_cap_drops_over():
    mw = ThrottleMiddleware()
    # Tighten the cap on the instance so the test stays self-contained.
    mw.MAX_EVENTS = 3
    mw.WINDOW_S = 60.0

    calls: list[str] = []

    async def handler(event, data):
        calls.append("ran")
        return "ok"

    msg = _make_message(uid=42)
    # First 3 within the window all go through.
    for _ in range(3):
        result = await mw(handler, msg, {})
        assert result == "ok"

    # The 4th gets dropped (handler not invoked, middleware returns None).
    result = await mw(handler, msg, {})
    assert result is None
    assert len(calls) == 3
