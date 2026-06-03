from __future__ import annotations

import pytest

from src.handlers import search_wizard


@pytest.mark.asyncio
async def test_fetch_results_forwards_hotel_name_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_search_hotels(**params):  # type: ignore[no-untyped-def]
        captured.update(params)
        return {"items": [], "total": 0, "limit": 60, "offset": 0}

    monkeypatch.setattr(search_wizard, "search_hotels", fake_search_hotels)

    await search_wizard._fetch_results({"q": "Rixos Premium", "nights": 7})

    assert captured["q"] == "Rixos Premium"
    assert captured["nights"] == 7
