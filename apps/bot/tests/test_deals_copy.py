from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import main as bot_main
from src.handlers import commands, deals, destinations, subscribe
from src.keyboards import main_menu


def _deal_row(**overrides):
    row = {
        "hotel_name_uk": "Albatros Dana Beach Resort",
        "hotel_stars": 5,
        "destination_name": "Хургада",
        "check_in": "2026-06-14",
        "nights": 7,
        "meal_plan": "AI",
        "discount_pct": 19,
        "price_uah": 104678,
        "baseline_p50": 128602,
        "detection_method": "calendar_anomaly",
        "deep_link": "https://farvater.travel/hotel/eg/albatros",
    }
    row.update(overrides)
    return row


def test_deals_page_header_uses_neutral_variant_copy() -> None:
    out = deals._render_page([_deal_row()], page=1, total_pages=2)

    assert "Гарячі варіанти" in out
    assert "зниж" not in out.casefold()


def test_best_header_uses_full_night_wording_and_neutral_copy() -> None:
    assert deals._best_header(None) == "🏆 *Топ\\-варіанти зараз*"

    out = deals._best_header((7, 7))

    assert "7 ночей" in out
    assert "ноч\\." not in out
    assert "зниж" not in out.casefold()


@pytest.mark.asyncio
async def test_best_subscribe_button_uses_neutral_variant_copy(monkeypatch) -> None:
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: type("Settings", (), {"public_site_url": "https://fasttravel.test"})(),
    )

    keyboard = await deals._best_keyboard([_deal_row()])
    labels = [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data == "best:subscribe"
    ]

    assert labels == ["🔔 Підписатись на цікаві варіанти"]


def test_destinations_copy_uses_neutral_variant_language() -> None:
    list_text = destinations._destinations_list_text()
    drill_header = destinations._country_drill_header("TR")
    empty_body = destinations._country_drill_empty_body()

    combined = "\n".join([list_text, drill_header, empty_body])

    assert "топ\\-варіанти" in list_text
    assert "топ варіантів" in drill_header
    assert "активних варіантів" in empty_body
    assert "зниж" not in combined.casefold()


def test_main_menu_and_public_commands_use_neutral_variant_copy() -> None:
    menu_labels = [
        main_menu.BEST,
        main_menu.DEALS,
        main_menu.SUBSCRIBE,
    ]
    command_descriptions = [command.description for command in bot_main.PUBLIC_COMMANDS]

    combined = "\n".join([*menu_labels, *command_descriptions])

    assert "варіант" in combined.casefold()
    assert "зниж" not in combined.casefold()


def test_subscriptions_header_uses_neutral_variant_copy() -> None:
    empty = subscribe._render_subscriptions([])
    filled = subscribe._render_subscriptions(
        [
            {
                "id": 1,
                "country_iso2": "TR",
                "max_price_uah": 50_000,
                "min_stars": 4,
            }
        ]
    )

    combined = "\n".join([empty, filled])

    assert "варіант" in combined.casefold()
    assert "зниж" not in combined.casefold()


@pytest.mark.asyncio
async def test_channel_copy_uses_neutral_variant_language(monkeypatch) -> None:
    monkeypatch.setattr(
        commands,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "public_channel_link": "https://t.me/fasttravel_deals",
                "public_site_url": None,
            },
        )(),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await commands.cmd_channel(message)

    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    button_labels = [button.text for row in markup.inline_keyboard for button in row]
    combined = "\n".join([text, *button_labels])

    assert "варіант" in combined.casefold()
    assert "зниж" not in combined.casefold()


@pytest.mark.asyncio
async def test_help_copy_uses_neutral_variant_language() -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await commands.cmd_help(message)

    text = message.answer.await_args.args[0]

    assert "варіант" in text.casefold()
    assert "зниж" not in text.casefold()


@pytest.mark.asyncio
async def test_best_nights_callback_answers_when_message_is_inaccessible(monkeypatch) -> None:
    query = SimpleNamespace(
        data="best:nights:7:7",
        message=None,
        answer=AsyncMock(),
    )
    monkeypatch.setattr(
        deals,
        "_send_best",
        AsyncMock(side_effect=AssertionError("message should not be edited")),
    )

    await deals.cb_best_nights(query)

    query.answer.assert_awaited_once_with("Повідомлення недоступне", show_alert=False)


@pytest.mark.asyncio
async def test_best_subscribe_callback_answers_when_message_is_inaccessible() -> None:
    query = SimpleNamespace(
        data="best:subscribe",
        message=None,
        answer=AsyncMock(),
    )

    await deals.cb_best_subscribe(query)

    query.answer.assert_awaited_once_with("Повідомлення недоступне", show_alert=False)
