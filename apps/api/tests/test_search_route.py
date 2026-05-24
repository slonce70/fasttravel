from __future__ import annotations

from datetime import date

import pytest

from src.schemas.search import PaginatedSearchResults


@pytest.mark.asyncio
async def test_search_route_normalizes_html_escaped_params_and_pax(client, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_search_hotels(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return PaginatedSearchResults(items=[], total=0, limit=20, offset=0)

    monkeypatch.setattr("src.routers.search.search_hotels", fake_search_hotels)

    resp = await client.get(
        "/api/search?country=TR&amp;nights=7&amp;meal_plan=AI"
        "&amp;stars_min=4&amp;adults=3&amp;kids=7"
    )

    assert resp.status_code == 200
    assert captured["country"] == "TR"
    assert captured["nights"] == 7
    assert captured["meal_plan"] == "AI"
    assert captured["stars_min"] == 4
    assert captured["adults"] == 3
    assert captured["kids"] == [7]


@pytest.mark.asyncio
async def test_search_route_passes_check_in_and_plain_params(client, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_search_hotels(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return PaginatedSearchResults(items=[], total=0, limit=50, offset=20)

    monkeypatch.setattr("src.routers.search.search_hotels", fake_search_hotels)

    resp = await client.get(
        "/api/search?country=EG&check_in=2026-06-01&nights=10"
        "&meal_plan=UAI&price_max=100000&stars_min=5&limit=50&offset=20"
    )

    assert resp.status_code == 200
    assert captured["country"] == "EG"
    assert captured["check_in"] == date(2026, 6, 1)
    assert captured["nights"] == 10
    assert captured["meal_plan"] == "UAI"
    assert captured["price_max"] == 100000
    assert captured["stars_min"] == 5
    assert captured["limit"] == 50
    assert captured["offset"] == 20
