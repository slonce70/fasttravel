from __future__ import annotations

from datetime import date
from http import HTTPStatus

import pytest
from fastapi import HTTPException

from src.routers.search import _parse_kids
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


@pytest.mark.asyncio
async def test_search_route_accepts_legacy_check_in_min(client, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_search_hotels(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return PaginatedSearchResults(items=[], total=0, limit=20, offset=0)

    monkeypatch.setattr("src.routers.search.search_hotels", fake_search_hotels)

    resp = await client.get("/api/search?country=TR&check_in_min=2026-06-15&nights=7")

    assert resp.status_code == 200
    assert captured["check_in"] == date(2026, 6, 15)


@pytest.mark.asyncio
@pytest.mark.parametrize("kids", ["abc", "-1", "7,nope", "18"])
async def test_search_route_rejects_invalid_kids(client, kids: str) -> None:
    resp = await client.get(f"/api/search?country=TR&kids={kids}")

    assert resp.status_code == 422


@pytest.mark.parametrize("kids", ["abc", "-1", "7,nope", "18"])
def test_parse_kids_rejects_invalid_values_without_db(kids: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _parse_kids(kids)

    assert exc_info.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_search_route_rejects_more_than_six_kids(client) -> None:
    resp = await client.get("/api/search?country=TR&kids=1,2,3,4,5,6,7")

    assert resp.status_code == 422


def test_parse_kids_rejects_more_than_six_values_without_db() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _parse_kids("1,2,3,4,5,6,7")

    assert exc_info.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_search_route_passes_sort_from_plain_and_html_escaped_params(
    client, monkeypatch
) -> None:
    captured: list[dict[str, object]] = []

    async def fake_search_hotels(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        return PaginatedSearchResults(items=[], total=0, limit=20, offset=0)

    monkeypatch.setattr("src.routers.search.search_hotels", fake_search_hotels)

    plain_resp = await client.get("/api/search?country=TR&sort=rating_desc")
    escaped_resp = await client.get("/api/search?country=TR&amp;sort=name_asc")

    assert plain_resp.status_code == 200
    assert escaped_resp.status_code == 200
    assert captured[0]["sort"] == "rating_desc"
    assert captured[1]["sort"] == "name_asc"
