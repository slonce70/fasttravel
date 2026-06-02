"""Tests for the «Найдешевші тури» surface (cheapest-tours, NOT discounts).

Mirrors test_deals_copy.py: pure-render assertions on the digest template,
plus the api_client + menu/command wiring. The honesty rule is enforced
here — «ціна від» present, «знижка» / «−X%» / strike-through absent.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import main as bot_main
from src.handlers import cheap, commands
from src.infra.api_client import ApiError
from src.keyboards import main_menu
from src.templates.cheap import (
    render_cheap_card,
    render_cheap_digest,
    telegram_parsed_len,
)


def _cheap_row(**overrides):
    row = {
        "country_iso2": "BG",
        "country_name": "Болгарія",
        "hotel_id": 46481,
        "hotel_slug": "fv-bg-chuchulev",
        "hotel_name": "Chuchulev Hotel",
        "stars": 3,
        "review_score": 9.2,
        "review_count": 4,
        "check_in": "2026-06-06",
        "nights": 7,
        "meal_plan": "RO",
        "price_uah": 18210,
        "deep_link": "https://farvater.travel/uk/hotel/bg/chuchulev?q=2m8493c8",
        "rank": 1,
    }
    row.update(overrides)
    return row


def test_card_uses_honest_cina_vid_copy_and_no_discount_signals() -> None:
    out = render_cheap_card(_cheap_row())

    assert "ціна від" in out
    assert "18 210 ₴" in out
    # Honesty rule: never a discount.
    assert "зниж" not in out.casefold()
    assert "%" not in out
    assert "~" not in out  # no struck-through baseline


def test_card_renders_deep_link_and_stars_and_reviews() -> None:
    out = render_cheap_card(_cheap_row())

    assert "Chuchulev Hotel" in out
    assert "⭐⭐⭐" in out
    assert "9\\.2/10" in out  # MarkdownV2-escaped decimal point
    assert "Переглянути →" in out
    assert "farvater.travel" in out


def test_card_drops_optional_blocks_when_absent() -> None:
    out = render_cheap_card(
        _cheap_row(review_score=None, review_count=0, deep_link=None)
    )

    assert "/10" not in out
    assert "Переглянути" not in out
    # Required blocks still present.
    assert "ціна від" in out


def test_digest_groups_by_country_in_one_pass() -> None:
    rows = [
        _cheap_row(country_iso2="BG", country_name="Болгарія", hotel_name="Bg A", rank=1),
        _cheap_row(country_iso2="BG", country_name="Болгарія", hotel_name="Bg B", rank=2),
        _cheap_row(country_iso2="EG", country_name="Єгипет", hotel_name="Eg A", rank=1),
    ]

    out = render_cheap_digest(rows)

    assert "Найдешевші тури по напрямках" in out
    assert "Болгарія" in out
    assert "Єгипет" in out
    assert "Bg A" in out and "Bg B" in out and "Eg A" in out
    assert "зниж" not in out.casefold()
    assert "%" not in out


def test_digest_empty_is_graceful_and_honest() -> None:
    out = render_cheap_digest([])

    assert "Найдешевші тури" in out
    assert "зниж" not in out.casefold()


def _big_rows(n_countries: int, per_country: int = 3) -> list:
    """Worst-case-ish rows: long hotel names + long deep links + reviews."""
    rows = []
    for i in range(n_countries):
        for r in range(1, per_country + 1):
            rows.append(
                _cheap_row(
                    country_iso2=f"C{i:02d}",
                    country_name=f"Дуже Довга Назва Країни {i}",
                    hotel_name=f"Long Hotel Name Resort & Spa {i}-{r}",
                    review_score=8.7,
                    review_count=1234,
                    deep_link=(
                        "https://farvater.travel/uk/hotel/bg/some-long-hotel-slug"
                        f"-here-{i}-{r}?q=2m8493723706596789963c8"
                    ),
                    rank=r,
                )
            )
    return rows


def test_telegram_parsed_len_ignores_hidden_urls_and_markdown() -> None:
    # The hidden URL and MarkdownV2 markers must not count toward the cap.
    with_link = "💰 ціна від *18 210 ₴*\n🛒 [Переглянути →](https://example.com/very/long/url?q=abc123)"
    no_link = "💰 ціна від 18 210 ₴\n🛒 Переглянути →"
    assert telegram_parsed_len(with_link) == telegram_parsed_len(no_link)


def test_digest_stays_under_telegram_cap_in_worst_case() -> None:
    out = render_cheap_digest(_big_rows(20))

    assert telegram_parsed_len(out) <= 4096
    # Always shows at least one country.
    assert "📍" in out


def test_digest_truncation_footer_points_to_site() -> None:
    out = render_cheap_digest(
        _big_rows(20), site_cheap_url="https://fasttravel.test/cheap"
    )

    shown = out.count("📍")
    assert shown < 20  # truncated
    assert "на сайті" in out
    assert "fasttravel.test/cheap" in out
    assert "зниж" not in out.casefold()


def test_digest_realistic_country_count_is_not_over_truncated() -> None:
    # 11 real countries with realistic 3-card sizes (contract-shaped names /
    # deep links) parse to ~4400, just over Telegram's 4096 cap, so not all
    # fit in one message. The length-aware builder must still show a healthy
    # majority (>=8) rather than gutting the "diverse across destinations"
    # goal with a too-tight cap — and must keep TOP-3 per country shown
    # (never thin cards per country to fit more).
    names = [
        "Болгарія", "Єгипет", "Туреччина", "Греція", "ОАЕ", "Кіпр",
        "Іспанія", "Чорногорія", "Албанія", "Туніс", "Грузія",
    ]
    rows = []
    for i, name in enumerate(names):
        for r in range(1, 4):
            rows.append(
                _cheap_row(
                    country_iso2=f"C{i:02d}",
                    country_name=name,
                    hotel_name=f"Topalovi Family Hotel {r}",
                    rank=r,
                )
            )

    out = render_cheap_digest(rows, site_cheap_url="https://fasttravel.test/cheap")

    shown = out.count("📍")
    assert shown >= 8  # healthy majority, not over-truncated
    assert telegram_parsed_len(out) <= 4096
    # Each shown country keeps all three of its TOP-3 cards (3 price lines
    # per country block — we never thin per-country to fit more). Count the
    # «💰 ціна від» card prefix so the footer's «ціна від» mention is excluded.
    assert out.count("💰 ціна від") == shown * 3
    # Truncated → footer points to the site so dropped countries aren't
    # silently presented as having no tours.
    assert "на сайті" in out


@pytest.mark.asyncio
async def test_get_cheapest_tours_returns_flat_list(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return [_cheap_row()]

    class _Client:
        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

    from src.infra import api_client

    monkeypatch.setattr(api_client, "get_client", lambda: _Client())

    result = await api_client.get_cheapest_tours()

    assert isinstance(result, list)
    assert result[0]["hotel_name"] == "Chuchulev Hotel"
    assert captured["url"] == "/api/cheapest-tours"
    assert captured["params"] == {"per_country": 3, "min_stars": 3}


@pytest.mark.asyncio
async def test_show_cheap_renders_digest(monkeypatch) -> None:
    monkeypatch.setattr(cheap, "get_cheapest_tours", AsyncMock(return_value=[_cheap_row()]))
    message = SimpleNamespace(answer=AsyncMock())

    await cheap.show_cheap(message)

    text = message.answer.await_args.args[0]
    assert "ціна від" in text
    assert "Болгарія" in text
    assert "зниж" not in text.casefold()


@pytest.mark.asyncio
async def test_show_cheap_handles_api_error(monkeypatch) -> None:
    monkeypatch.setattr(
        cheap, "get_cheapest_tours", AsyncMock(side_effect=ApiError("boom"))
    )
    message = SimpleNamespace(answer=AsyncMock())

    await cheap.show_cheap(message)

    text = message.answer.await_args.args[0]
    assert "тимчасово недоступний" in text


@pytest.mark.asyncio
async def test_text_cheap_bridge_clears_state_and_shows(monkeypatch) -> None:
    monkeypatch.setattr(cheap, "get_cheapest_tours", AsyncMock(return_value=[_cheap_row()]))
    message = SimpleNamespace(answer=AsyncMock())
    state = SimpleNamespace(clear=AsyncMock())

    await commands.text_cheap(message, state)

    state.clear.assert_awaited_once()
    message.answer.assert_awaited()


def test_menu_and_commands_register_cheap_with_neutral_copy() -> None:
    assert main_menu.CHEAP in {
        button.text
        for row in main_menu.main_menu_kb().keyboard
        for button in row
    }
    cheap_cmds = [c for c in bot_main.PUBLIC_COMMANDS if c.command == "cheap"]
    assert len(cheap_cmds) == 1
    assert "зниж" not in cheap_cmds[0].description.casefold()
