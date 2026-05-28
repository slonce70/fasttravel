from __future__ import annotations

from typing import Any

import pytest

from src.services import materialized_views


class _FakeConnection:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.options: list[dict[str, Any]] = []
        self.statements: list[str] = []
        self.fail_first = fail_first

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execution_options(self, **kwargs: Any) -> _FakeConnection:
        self.options.append(kwargs)
        return self

    async def execute(self, sql: Any) -> None:
        statement = str(sql)
        self.statements.append(statement)
        if self.fail_first and len(self.statements) == 1:
            raise RuntimeError("mv has not been populated")


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


@pytest.mark.asyncio
async def test_refresh_price_views_uses_autocommit_concurrent_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(materialized_views, "async_engine", _FakeEngine(connection))

    results = await materialized_views.refresh_price_views()

    assert connection.options == [{"isolation_level": "AUTOCOMMIT"}]
    assert connection.statements == [
        "REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY hotel_calendar_prices",
    ]
    assert results == {
        "current_prices": "concurrent",
        "hotel_calendar_prices": "concurrent",
    }


def test_price_refresh_views_exclude_price_baselines() -> None:
    assert materialized_views.PRICE_REFRESH_VIEWS == (
        "current_prices",
        "hotel_calendar_prices",
    )
    assert "price_baselines" not in materialized_views.PRICE_REFRESH_VIEWS


@pytest.mark.asyncio
async def test_refresh_materialized_views_falls_back_only_for_unpopulated_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(fail_first=True)
    monkeypatch.setattr(materialized_views, "async_engine", _FakeEngine(connection))
    monkeypatch.setattr(materialized_views, "_is_unpopulated_view_error", lambda _exc: True)

    results = await materialized_views.refresh_materialized_views(("current_prices",))

    assert connection.statements == [
        "REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices",
        "REFRESH MATERIALIZED VIEW current_prices",
    ]
    assert results == {"current_prices": "blocking"}
