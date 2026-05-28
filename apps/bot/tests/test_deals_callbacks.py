from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.handlers import deals


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_data", ["best:nights:10:7", "best:nights:0:7"])
async def test_best_nights_ignores_invalid_ranges(monkeypatch, callback_data: str) -> None:
    message = SimpleNamespace()
    query = SimpleNamespace(
        data=callback_data,
        message=message,
        answer=AsyncMock(),
    )
    send_best = AsyncMock()
    monkeypatch.setattr(deals, "callback_message", lambda _query: message)
    monkeypatch.setattr(deals, "_send_best", send_best)

    await deals.cb_best_nights(query)  # type: ignore[arg-type]

    send_best.assert_not_awaited()
    query.answer.assert_awaited_once_with()
