from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.handlers import search_wizard


def test_results_header_pluralizes_tours() -> None:
    assert search_wizard._format_results_header(total=1, page=1, total_pages=1) == (
        "✅ Знайдено *1* тур · сторінка *1/1*"
    )
    assert search_wizard._format_results_header(total=2, page=1, total_pages=1) == (
        "✅ Знайдено *2* тури · сторінка *1/1*"
    )
    assert search_wizard._format_results_header(total=5, page=1, total_pages=1) == (
        "✅ Знайдено *5* турів · сторінка *1/1*"
    )


class FakeState:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def update_data(self, *args, **kwargs) -> None:
        if args:
            self.data.update(args[0])
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.data["state"] = state


@pytest.mark.asyncio
async def test_results_subscribe_creates_real_filter_and_hides_button(monkeypatch) -> None:
    ensure = AsyncMock()
    add = AsyncMock(return_value=77)
    monkeypatch.setattr(search_wizard, "ensure_subscriber", ensure)
    monkeypatch.setattr(search_wizard, "add_subscription", add)

    message = SimpleNamespace(edit_reply_markup=AsyncMock())
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=12345, username="traveler"),
        message=message,
        answer=AsyncMock(),
    )
    monkeypatch.setattr(search_wizard, "callback_message", lambda _query: message)
    state = FakeState(
        {
            "country": "TR",
            "price_max": 50000,
            "stars_min": 4,
            "meal_plan": "AI",
            "page": 1,
            "results": {
                "total": 1,
                "items": [
                    {
                        "name_uk": "Belport Beach",
                        "canonical_slug": "fv-tr-belport-beach",
                        "deep_link": "https://farvater.travel/?q=abc",
                    }
                ],
            },
        }
    )

    await search_wizard.cb_subscribe(query, state)

    ensure.assert_awaited_once_with(12345, "traveler")
    add.assert_awaited_once_with(
        12345,
        country_iso2="TR",
        max_price_uah=50000,
        min_stars=4,
        meal_plan="AI",
    )
    assert state.data["subscribed"] is True
    query.answer.assert_awaited_once_with(
        "Підписка #77 створена: країна, бюджет, зірковість і харчування",
        show_alert=True,
    )

    message.edit_reply_markup.assert_awaited_once()
    markup = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "res:subscribe" not in callbacks


@pytest.mark.asyncio
async def test_search_nights_ignores_malformed_callback_without_mutating_state(monkeypatch) -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    query = SimpleNamespace(
        data="n:not-a-number",
        message=message,
        answer=AsyncMock(),
    )
    monkeypatch.setattr(search_wizard, "callback_message", lambda _query: message)
    state = FakeState({"country": "TR"})

    await search_wizard.cb_nights(query, state)

    assert "nights" not in state.data
    assert "state" not in state.data
    message.edit_text.assert_not_awaited()
    query.answer.assert_awaited_once_with()
