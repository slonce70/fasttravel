"""Pure-function tests for keyboard factories.

No Telegram or DB involvement — just verifies that the InlineKeyboardMarkup
shape, callback_data prefixes, and row counts match what handlers expect.
A regression here surfaces as a wrong callback prefix and breaks the wizard,
so the tests are cheap insurance.
"""

from __future__ import annotations

from src.keyboards.countries import countries_kb, country_emoji
from src.keyboards.filters import (
    budget_kb,
    meal_kb,
    nights_kb,
    results_actions_kb,
    stars_kb,
    when_kb,
)
from src.keyboards.main_menu import (
    DEALS,
    DESTINATIONS,
    HELP,
    PROFILE,
    SEARCH,
    SUBSCRIBE,
    main_menu_kb,
)


def _all_callbacks(kb) -> list[str]:
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_main_menu_has_six_labels_in_three_rows():
    kb = main_menu_kb()
    assert len(kb.keyboard) == 3
    assert [b.text for row in kb.keyboard for b in row] == [
        SEARCH, DEALS, DESTINATIONS, SUBSCRIBE, PROFILE, HELP,
    ]


def test_country_emoji_known_iso():
    assert country_emoji("TR") == "🇹🇷"
    assert country_emoji("XX") == "📍"  # unknown falls back


def test_countries_kb_two_columns_and_skips_zero_count():
    destinations = [
        {"country_iso2": "TR", "name_uk": "Туреччина", "hotel_count": 1130},
        {"country_iso2": "EG", "name_uk": "Єгипет", "hotel_count": 820},
        {"country_iso2": "GR", "name_uk": "Греція", "hotel_count": 0},  # skipped
    ]
    kb = countries_kb(destinations)
    assert len(kb.inline_keyboard) >= 1
    # First row has 2 columns; cancel row at the bottom is single col
    assert len(kb.inline_keyboard[0]) == 2
    cbs = _all_callbacks(kb)
    assert "cc:TR" in cbs
    assert "cc:EG" in cbs
    assert "cc:GR" not in cbs
    assert "cc:cancel" in cbs


def test_nights_kb_callback_shape():
    cbs = _all_callbacks(nights_kb())
    assert {"n:3", "n:5", "n:7", "n:10", "n:14", "n:21", "n:any", "n:back"} <= set(cbs)


def test_when_kb_callbacks():
    cbs = _all_callbacks(when_kb())
    assert {"w:soon", "w:month", "w:season", "w:any", "w:back"} <= set(cbs)


def test_budget_kb_callbacks():
    cbs = _all_callbacks(budget_kb())
    assert {"b:30000", "b:50000", "b:80000", "b:120000", "b:premium", "b:any", "b:back"} <= set(cbs)


def test_meal_kb_callbacks():
    cbs = _all_callbacks(meal_kb())
    assert {"m:AI", "m:HB", "m:BB", "m:RO", "m:any", "m:back"} <= set(cbs)


def test_stars_kb_callbacks():
    cbs = _all_callbacks(stars_kb())
    assert {"s:3", "s:4", "s:5", "s:any", "s:back"} <= set(cbs)


def test_results_actions_kb_pagination_states():
    kb = results_actions_kb(has_prev=False, has_next=True, page=1, total_pages=3, subscription_set=False)
    cbs = _all_callbacks(kb)
    # No "prev" on first page
    assert "res:prev" not in cbs
    assert "res:next" in cbs
    # "Subscribe" appears when subscription_set=False
    assert "res:subscribe" in cbs

    kb = results_actions_kb(has_prev=True, has_next=False, page=3, total_pages=3, subscription_set=True)
    cbs = _all_callbacks(kb)
    assert "res:prev" in cbs
    assert "res:next" not in cbs
    # No "Subscribe" once user already subscribed
    assert "res:subscribe" not in cbs


def test_results_actions_kb_indicator_shows_page_total():
    kb = results_actions_kb(has_prev=True, has_next=True, page=2, total_pages=5, subscription_set=False)
    nav_row_texts = [b.text for b in kb.inline_keyboard[0]]
    assert any("2/5" in t for t in nav_row_texts)
