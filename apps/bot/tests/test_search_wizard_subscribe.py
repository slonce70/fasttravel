from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.handlers import search_wizard, wizard_render


def test_results_header_pluralizes_tours() -> None:
    assert wizard_render.format_results_header(total=1, page=1, total_pages=1) == (
        "✅ Знайдено *1* тур · сторінка *1/1*"
    )
    assert wizard_render.format_results_header(total=2, page=1, total_pages=1) == (
        "✅ Знайдено *2* тури · сторінка *1/1*"
    )
    assert wizard_render.format_results_header(total=5, page=1, total_pages=1) == (
        "✅ Знайдено *5* турів · сторінка *1/1*"
    )


def test_results_header_qualifies_when_total_exceeds_browsable() -> None:
    # The wizard caches only the first 60 hits and never refetches on a page
    # turn. When the catalog has more matches than that, the header must say
    # so honestly instead of implying all `total` tours are reachable.
    header = wizard_render.format_results_header(total=200, page=1, total_pages=12, shown=60)
    assert "Знайдено *200* турів" in header
    assert "показано перші *60*" in header
    assert "сторінка *1/12*" in header


def test_results_header_no_qualifier_when_all_browsable() -> None:
    # When everything found fits in the cached page, no "показано перші"
    # qualifier — it would be noise (and misleading).
    header = wizard_render.format_results_header(total=12, page=1, total_pages=3, shown=12)
    assert "показано перші" not in header
    assert header == "✅ Знайдено *12* турів · сторінка *1/3*"


def test_step_prefix_maps_each_step_to_its_index() -> None:
    # /help advertises a "майстер з 7 кроків"; the prefixes must match that
    # count and order so advertised and actual stay in sync.
    assert wizard_render.WIZARD_STEP_COUNT == 7
    assert wizard_render.step_prefix("hotel") == "Крок 1/7 · "
    assert wizard_render.step_prefix("country") == "Крок 2/7 · "
    assert wizard_render.step_prefix("nights") == "Крок 3/7 · "
    assert wizard_render.step_prefix("when") == "Крок 4/7 · "
    assert wizard_render.step_prefix("budget") == "Крок 5/7 · "
    assert wizard_render.step_prefix("meal") == "Крок 6/7 · "
    assert wizard_render.step_prefix("stars") == "Крок 7/7 · "


def test_step_prefix_unknown_step_is_empty() -> None:
    assert wizard_render.step_prefix("nope") == ""


def test_when_bucket_range_maps_buckets_to_inclusive_date_windows() -> None:
    # Each "when" bucket is a *range* of check-in days, not one pinned day.
    # The old behaviour stored a single date (today+7/+30/+60) and queried
    # exact-day match, so window-labelled buckets matched almost nothing.
    today = date(2026, 6, 1)

    soon = search_wizard.when_bucket_range("soon", today=today)
    assert soon == ("2026-06-01", "2026-06-22")  # today .. +21

    month = search_wizard.when_bucket_range("month", today=today)
    assert month == ("2026-06-23", "2026-07-16")  # +22 .. +45

    season = search_wizard.when_bucket_range("season", today=today)
    assert season == ("2026-07-17", "2026-08-30")  # +46 .. +90

    # The windows are contiguous and non-overlapping (no gap, no double-count).
    assert soon[1] < month[0]
    assert month[1] < season[0]


def test_when_bucket_range_any_and_unknown_are_no_filter() -> None:
    assert search_wizard.when_bucket_range("any", today=date(2026, 6, 1)) is None
    assert search_wizard.when_bucket_range("garbage", today=date(2026, 6, 1)) is None


@pytest.mark.asyncio
async def test_results_subscribe_reuses_existing_subscription(monkeypatch) -> None:
    # A second subscribe with the same natural key must NOT INSERT a duplicate
    # (which would double the alert DMs); it reuses the existing id and tells
    # the user. This is the conservative dedup contract.
    ensure = AsyncMock()
    add = AsyncMock(return_value=999)
    find = AsyncMock(return_value=42)
    monkeypatch.setattr(search_wizard, "ensure_subscriber", ensure)
    monkeypatch.setattr(search_wizard, "add_subscription", add)
    monkeypatch.setattr(search_wizard, "find_subscription", find)
    monkeypatch.setattr(
        search_wizard,
        "get_settings",
        lambda: SimpleNamespace(public_site_url=None),
    )

    message = SimpleNamespace(edit_reply_markup=AsyncMock())
    monkeypatch.setattr(search_wizard, "callback_message", lambda _query: message)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=12345, username="traveler"),
        message=message,
        answer=AsyncMock(),
    )
    state = FakeState(
        {
            "country": "TR",
            "price_max": None,
            "stars_min": None,
            "meal_plan": None,
            "page": 1,
            "results": {"total": 1, "items": [{"name_uk": "H", "canonical_slug": "fv-tr-h"}]},
        }
    )

    await search_wizard.cb_subscribe(query, state)

    find.assert_awaited_once_with(
        12345,
        country_iso2="TR",
        max_price_uah=None,
        min_stars=None,
        meal_plan=None,
    )
    add.assert_not_awaited()  # the whole point — no duplicate row
    query.answer.assert_awaited_once_with(
        "Ви вже маєте таку підписку — нову не створювали",
        show_alert=True,
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
    find = AsyncMock(return_value=None)
    monkeypatch.setattr(search_wizard, "ensure_subscriber", ensure)
    monkeypatch.setattr(search_wizard, "add_subscription", add)
    monkeypatch.setattr(search_wizard, "find_subscription", find)

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


def _capturing_markup(captured: dict[str, Any]):
    def _fake(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(inline_keyboard=[])

    return _fake


@pytest.mark.asyncio
async def test_show_results_threads_public_site_url_into_markup(monkeypatch) -> None:
    # Initial render path: _show_results must pass settings.public_site_url
    # through to results_markup so per-hit site buttons can be built.
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        search_wizard,
        "get_settings",
        lambda: SimpleNamespace(public_site_url="https://site.example"),
    )
    monkeypatch.setattr(search_wizard, "render_search_hit", lambda _h: "hit")
    monkeypatch.setattr(search_wizard, "results_markup", _capturing_markup(captured))
    message = SimpleNamespace(edit_text=AsyncMock())
    monkeypatch.setattr(search_wizard, "callback_message", lambda _query: message)
    query = SimpleNamespace(message=message, answer=AsyncMock())
    state = FakeState(
        {
            "page": 1,
            "results": {
                "total": 1,
                "items": [
                    {
                        "name_uk": "H",
                        "canonical_slug": "fv-tr-h",
                        "deep_link": "https://op/x",
                    }
                ],
            },
        }
    )

    await search_wizard._show_results(query, state, edit=True)

    assert captured.get("site_base_url") == "https://site.example"


@pytest.mark.asyncio
async def test_subscribe_rerender_threads_public_site_url_into_markup(monkeypatch) -> None:
    # Subscribe re-render path: cb_subscribe rebuilds the markup to hide the
    # subscribe button and must thread the same site URL through.
    captured: dict[str, Any] = {}
    monkeypatch.setattr(search_wizard, "ensure_subscriber", AsyncMock())
    monkeypatch.setattr(search_wizard, "add_subscription", AsyncMock(return_value=1))
    monkeypatch.setattr(search_wizard, "find_subscription", AsyncMock(return_value=None))
    monkeypatch.setattr(
        search_wizard,
        "get_settings",
        lambda: SimpleNamespace(public_site_url="https://site.example"),
    )
    monkeypatch.setattr(search_wizard, "results_markup", _capturing_markup(captured))
    message = SimpleNamespace(edit_reply_markup=AsyncMock())
    monkeypatch.setattr(search_wizard, "callback_message", lambda _query: message)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=1, username="u"),
        message=message,
        answer=AsyncMock(),
    )
    state = FakeState(
        {
            "country": "TR",
            "page": 1,
            "results": {
                "total": 1,
                "items": [
                    {
                        "name_uk": "H",
                        "canonical_slug": "fv-tr-h",
                        "deep_link": "https://op/x",
                    }
                ],
            },
        }
    )

    await search_wizard.cb_subscribe(query, state)

    assert captured.get("site_base_url") == "https://site.example"
