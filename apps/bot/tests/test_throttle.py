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


@pytest.mark.asyncio
async def test_throttle_sweeps_idle_user_keys(monkeypatch):
    """The per-user deque dict must reclaim entries for users whose window
    has fully emptied — otherwise it grows one entry per all-time unique
    user (a slow leak). The periodic sweep drops empty keys."""
    clock = {"now": 1000.0}
    monkeypatch.setattr("src.infra.middleware.time.monotonic", lambda: clock["now"])

    mw = ThrottleMiddleware()
    mw.WINDOW_S = 10.0
    mw.SWEEP_INTERVAL_S = 60.0

    async def handler(event, data):
        return "ok"

    # User A interacts once.
    await mw(handler, _make_message(uid=111), {})
    assert 111 in mw._events

    # Advance past both the window and the sweep interval, then a DIFFERENT
    # user interacts — that call triggers the sweep, which should reclaim the
    # now-idle user-A key (its single timestamp is older than now-WINDOW_S).
    clock["now"] += 100.0
    await mw(handler, _make_message(uid=222), {})

    assert 111 not in mw._events  # reclaimed
    assert 222 in mw._events  # the active user stays


@pytest.mark.asyncio
async def test_throttle_sweep_keeps_recently_active_users(monkeypatch):
    """A user still inside their window must NOT be reclaimed by a sweep."""
    clock = {"now": 5000.0}
    monkeypatch.setattr("src.infra.middleware.time.monotonic", lambda: clock["now"])

    mw = ThrottleMiddleware()
    mw.WINDOW_S = 100.0
    mw.SWEEP_INTERVAL_S = 1.0

    async def handler(event, data):
        return "ok"

    await mw(handler, _make_message(uid=111), {})
    # Advance past the sweep interval but stay well inside the 100s window.
    clock["now"] += 5.0
    await mw(handler, _make_message(uid=222), {})

    assert 111 in mw._events  # still within window — kept
    assert 222 in mw._events
