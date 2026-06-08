from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ParseMode

from src.handlers import deals


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_data", ["best:nights:10:7", "best:nights:0:7"])
async def test_best_nights_ignores_invalid_ranges(
    monkeypatch: pytest.MonkeyPatch, callback_data: str
) -> None:
    message = SimpleNamespace()
    query = SimpleNamespace(
        data=callback_data,
        message=message,
        answer=AsyncMock(),
    )
    send_best = AsyncMock()
    monkeypatch.setattr(deals, "callback_message", lambda _query: message)
    monkeypatch.setattr(deals, "_send_best", send_best)

    await deals.cb_best_nights(query)

    send_best.assert_not_awaited()
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_deals_page_edit_failure_sends_fresh_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deals,
        "get_deals",
        AsyncMock(
            return_value={
                "items": [
                    {
                        "discount_pct": 30,
                        "hotel_name_uk": "Unsafe Deal",
                        "hotel_slug": "fv-tr-unsafe-deal",
                        "deep_link": "javascript:alert(1)",
                        "check_in": "2026-06-14",
                        "nights": 7,
                        "meal_plan": "AI",
                        "price_uah": 30000,
                        "baseline_p50": 43000,
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: SimpleNamespace(public_site_url="https://fasttravel.test"),
    )
    message = SimpleNamespace(
        edit_text=AsyncMock(side_effect=RuntimeError("edit failed")),
        answer=AsyncMock(),
    )

    await deals._send_page(message, page=1, edit=True)  # type: ignore[arg-type]

    message.edit_text.assert_awaited_once()
    message.answer.assert_awaited_once()
    call = message.answer.await_args
    assert call.kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
    assert call.kwargs["disable_web_page_preview"] is True
    assert call.kwargs["reply_markup"].inline_keyboard[0][0].url == (
        "https://fasttravel.test/hotels/fv-tr-unsafe-deal?utm_source=tg_bot&utm_medium=deals"
    )


@pytest.mark.asyncio
async def test_best_edit_failure_sends_fresh_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        deals,
        "get_deals",
        AsyncMock(
            return_value={
                "items": [
                    {
                        "discount_pct": 30,
                        "hotel_name_uk": "Unsafe Best",
                        "hotel_slug": "fv-tr-unsafe-best",
                        "deep_link": " data:text/html,bad ",
                        "check_in": "2026-06-14",
                        "nights": 7,
                        "meal_plan": "AI",
                        "price_uah": 30000,
                        "baseline_p50": 43000,
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: SimpleNamespace(public_site_url="https://fasttravel.test"),
    )
    message = SimpleNamespace(
        edit_text=AsyncMock(side_effect=RuntimeError("edit failed")),
        answer=AsyncMock(),
    )

    await deals._send_best(message, nights_filter=None, edit=True)  # type: ignore[arg-type]

    message.edit_text.assert_awaited_once()
    message.answer.assert_awaited_once()
    call = message.answer.await_args
    assert call.kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
    assert call.kwargs["disable_web_page_preview"] is True
    assert call.kwargs["reply_markup"].inline_keyboard[1][0].url == (
        "https://fasttravel.test/hotels/fv-tr-unsafe-best?utm_source=tg_bot&utm_medium=best"
    )


@pytest.mark.asyncio
async def test_best_not_modified_edit_error_does_not_send_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deals,
        "get_deals",
        AsyncMock(
            return_value={
                "items": [
                    {
                        "discount_pct": 30,
                        "hotel_name_uk": "Same Best",
                        "hotel_slug": "fv-tr-same-best",
                        "deep_link": "https://operator.test/same",
                        "check_in": "2026-06-14",
                        "nights": 7,
                        "meal_plan": "AI",
                        "price_uah": 30000,
                        "baseline_p50": 43000,
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: SimpleNamespace(public_site_url="https://fasttravel.test"),
    )
    message = SimpleNamespace(
        edit_text=AsyncMock(side_effect=RuntimeError("Bad Request: message is not modified")),
        answer=AsyncMock(),
    )

    await deals._send_best(message, nights_filter=(7, 7), edit=True)  # type: ignore[arg-type]

    message.edit_text.assert_awaited_once()
    message.answer.assert_not_awaited()
