from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.handlers import destinations


class FakeState:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = dict(data or {})
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()

    async def update_data(self, *args, **kwargs) -> None:
        if args:
            self.data.update(args[0])
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.data["state"] = state


@pytest.mark.asyncio
async def test_search_in_country_ignores_malformed_callback_without_mutating_state(
    monkeypatch,
) -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    query = SimpleNamespace(data="ds:search", message=message, answer=AsyncMock())
    monkeypatch.setattr(destinations, "callback_message", lambda _query: message)
    state = FakeState({"existing": "value"})

    await destinations.cb_search_in_country(query, state)  # type: ignore[arg-type]

    assert state.data == {"existing": "value"}
    assert state.cleared is False
    message.edit_text.assert_not_awaited()
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_country_drill_ignores_empty_callback_without_fetching_deals(
    monkeypatch,
) -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    query = SimpleNamespace(data="ds:", message=message, answer=AsyncMock())
    get_deals = AsyncMock()
    monkeypatch.setattr(destinations, "callback_message", lambda _query: message)
    monkeypatch.setattr(destinations, "get_deals", get_deals)

    await destinations.cb_country_drill(query)  # type: ignore[arg-type]

    get_deals.assert_not_awaited()
    message.edit_text.assert_not_awaited()
    query.answer.assert_awaited_once_with()
