"""Aiogram middlewares — observability + anti-flood.

* `MetricsMiddleware` — wraps every handler in BOT_MESSAGES counter +
  BOT_HANDLER_LATENCY histogram. Tags by router name so we can spot
  which surface gets hammered.

* `ThrottleMiddleware` — per-user rate limit using an in-memory sliding
  window. 20 events per 10 seconds; over that we silently drop the
  update (with a structlog warning). Cheap defence against accidental
  bot spam from a frozen client.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.infra.logging import get_logger
from src.infra.metrics import BOT_HANDLER_LATENCY, BOT_MESSAGES

log = get_logger(__name__)


class MetricsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Router-level handler name resolves at dispatch time; we read it
        # from the matched router on the event_context if available.
        router = data.get("event_router")
        handler_name = router.name if router is not None else "unknown"
        t0 = time.perf_counter()
        try:
            result = await handler(event, data)
            BOT_MESSAGES.labels(handler=handler_name, outcome="ok").inc()
            return result
        except Exception:
            BOT_MESSAGES.labels(handler=handler_name, outcome="error").inc()
            raise
        finally:
            BOT_HANDLER_LATENCY.labels(handler=handler_name).observe(
                time.perf_counter() - t0
            )


class ThrottleMiddleware(BaseMiddleware):
    """Per-user sliding window. Drops events past the cap with a warning.

    `WINDOW_S` chosen at 10s and `MAX_EVENTS` at 20 — generous enough that
    normal interaction (wizard step taps) never hits it; short enough that
    a runaway client can't queue minutes of work.
    """

    WINDOW_S = 10.0
    MAX_EVENTS = 20

    def __init__(self) -> None:
        self._events: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message | CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        window = self._events[user_id]
        cutoff = now - self.WINDOW_S
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.MAX_EVENTS:
            log.warning(
                "bot.throttle.dropped",
                user_id=user_id,
                in_window=len(window),
                window_s=self.WINDOW_S,
            )
            BOT_MESSAGES.labels(handler="throttle", outcome="dropped").inc()
            # For callbacks we still answer() to dismiss the spinner, but
            # don't dispatch to the real handler.
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Зачекайте секунду…", show_alert=False)
                except Exception:  # noqa: BLE001
                    pass
            return None
        window.append(now)
        return await handler(event, data)
