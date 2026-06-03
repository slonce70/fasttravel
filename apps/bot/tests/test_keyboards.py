"""Pure-function tests for keyboard factories.

No Telegram or DB involvement — just verifies that the InlineKeyboardMarkup
shape, callback_data prefixes, and row counts match what handlers expect.
A regression here surfaces as a wrong callback prefix and breaks the wizard,
so the tests are cheap insurance.
"""

from __future__ import annotations

from src.keyboards.countries import countries_kb, country_emoji, country_name_uk
from src.keyboards.filters import (
    budget_kb,
    meal_kb,
    nights_kb,
    results_actions_kb,
    stars_kb,
    when_kb,
)
from src.keyboards.main_menu import (
    BEST,
    CHEAP,
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


def test_main_menu_layout():
    """Task clusters: intent tools (search/destinations), then the three
    browse feeds (best/deals/cheap), then account (subscribe/profile/help).
    Constants are imported by name so label-string changes flow through
    automatically; this locks the grouping + order."""
    kb = main_menu_kb()
    assert len(kb.keyboard) == 3
    assert [b.text for b in kb.keyboard[0]] == [SEARCH, DESTINATIONS]
    assert [b.text for b in kb.keyboard[1]] == [BEST, DEALS, CHEAP]
    assert [b.text for b in kb.keyboard[2]] == [SUBSCRIBE, PROFILE, HELP]


def test_main_menu_labels_are_unique_and_honest():
    """🔥 must be unique to DEALS (hot tours); CHEAP uses 💰 to match its
    «ціна від» framing and de-collide from the deal feed."""
    labels = [BEST, SEARCH, DEALS, CHEAP, DESTINATIONS, SUBSCRIBE, PROFILE, HELP]
    assert len(labels) == len(set(labels))  # no duplicate labels
    assert CHEAP.startswith("💰")  # price-from framing, not a discount
    assert DEALS.startswith("🔥")  # 🔥 is unique to the hot-tours feed
    assert sum(1 for label in labels if label.startswith("🔥")) == 1


def test_country_emoji_known_iso():
    assert country_emoji("TR") == "🇹🇷"
    assert country_emoji("XX") == "📍"  # unknown falls back


def test_country_name_uk_known():
    assert country_name_uk("TR") == "Туреччина"
    assert country_name_uk("EG") == "Єгипет"
    assert country_name_uk("AE") == "ОАЕ"


def test_country_name_uk_unknown_falls_back_to_iso():
    assert country_name_uk("XX") == "XX"


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


def test_countries_kb_pluralizes_hotel_counts():
    destinations = [
        {"country_iso2": "TR", "name_uk": "Туреччина", "hotel_count": 1},
        {"country_iso2": "EG", "name_uk": "Єгипет", "hotel_count": 2},
        {"country_iso2": "AE", "name_uk": "ОАЕ", "hotel_count": 5},
    ]

    labels = [b.text for row in countries_kb(destinations).inline_keyboard for b in row]

    assert "🇹🇷 Туреччина (1 готель)" in labels
    assert "🇪🇬 Єгипет (2 готелі)" in labels
    assert "🇦🇪 ОАЕ (5 готелів)" in labels


def test_nights_kb_callback_shape():
    cbs = _all_callbacks(nights_kb())
    assert {f"n:{n}" for n in range(7, 15)} | {"n:any", "n:back"} <= set(cbs)
    assert {"n:3", "n:5", "n:21"}.isdisjoint(cbs)


def test_nights_kb_uses_full_ukrainian_night_labels():
    labels = [b.text for row in nights_kb().inline_keyboard for b in row]

    assert "7 ночей ⭐" in labels
    assert "8 ночей" in labels
    assert "10 ночей" in labels
    assert all(not label.endswith(" ноч") for label in labels)


def test_when_kb_callbacks():
    cbs = _all_callbacks(when_kb())
    assert {"w:soon", "w:month", "w:season", "w:any", "w:back"} <= set(cbs)


def test_budget_kb_callbacks():
    cbs = _all_callbacks(budget_kb())
    assert {
        "b:30000",
        "b:50000",
        "b:80000",
        "b:120000",
        "b:any",
        "b:back",
    } <= set(cbs)


def test_budget_kb_has_no_premium_button():
    """The «Преміум 120+» button was a silent no-op: the API has no price
    floor, so it sent the exact same unfiltered query as «Без обмежень».
    Dropping it removes the duplicate path entirely."""
    cbs = _all_callbacks(budget_kb())
    assert "b:premium" not in cbs
    labels = [b.text for row in budget_kb().inline_keyboard for b in row]
    assert "Преміум 120+" not in labels


def test_budget_kb_labels_are_ceilings_not_ranges():
    """Budget callbacks set a single price ceiling, so the labels must read
    «до N ₴» — matching the subscribe wizard — not misleading «30-50 тис»
    ranges (which would imply a floor the API can't express)."""
    labels = [b.text for row in budget_kb().inline_keyboard for b in row]
    assert "до 30 000 ₴" in labels
    assert "до 50 000 ₴" in labels
    assert "до 80 000 ₴" in labels
    assert "до 120 000 ₴" in labels
    assert "Без обмежень" in labels
    # No range-style label survives.
    assert all("-" not in label for label in labels if "₴" in label or "тис" in label)
    assert not any("тис" in label for label in labels)


def test_meal_kb_callbacks():
    cbs = _all_callbacks(meal_kb())
    assert {"m:AI", "m:HB", "m:BB", "m:RO", "m:any", "m:back"} <= set(cbs)


def test_stars_kb_callbacks():
    cbs = _all_callbacks(stars_kb())
    assert {"s:3", "s:4", "s:5", "s:any", "s:back"} <= set(cbs)


def test_results_actions_kb_pagination_states():
    kb = results_actions_kb(
        has_prev=False, has_next=True, page=1, total_pages=3, subscription_set=False
    )
    cbs = _all_callbacks(kb)
    # No "prev" on first page
    assert "res:prev" not in cbs
    assert "res:next" in cbs
    # "Subscribe" appears when subscription_set=False
    assert "res:subscribe" in cbs
    assert any(b.text == "🔔 Алерт за цими фільтрами" for row in kb.inline_keyboard for b in row)

    kb = results_actions_kb(
        has_prev=True, has_next=False, page=3, total_pages=3, subscription_set=True
    )
    cbs = _all_callbacks(kb)
    assert "res:prev" in cbs
    assert "res:next" not in cbs
    # No "Subscribe" once user already subscribed
    assert "res:subscribe" not in cbs


def test_results_actions_kb_indicator_shows_page_total():
    kb = results_actions_kb(
        has_prev=True, has_next=True, page=2, total_pages=5, subscription_set=False
    )
    nav_row_texts = [b.text for b in kb.inline_keyboard[0]]
    assert any("2/5" in t for t in nav_row_texts)
