"""Subscriber-filter dedup tests for the bot DB helpers.

The bot test suite has no live Postgres fixture (every other test mocks the
session), so we exercise ``find_subscription`` against a fake session that
captures the SQL and returns a scripted row. The critical contract being
locked is the NULL-safe comparison: a "no limit" subscription has NULL
``max_price_uah`` / ``min_stars`` / ``meal_plan`` (the common case), and a
plain ``= :x`` would never re-match those, silently defeating dedup. We assert
the helper uses ``IS NOT DISTINCT FROM`` for the three nullable columns.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.infra.db as db_mod


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class _FakeSession:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self.executed_sql = ""
        self.executed_params: dict[str, Any] = {}

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, sql, params):  # type: ignore[no-untyped-def]
        self.executed_sql = str(sql)
        self.executed_params = params
        return _FakeResult(self._row)


def _install_fake_factory(monkeypatch, row: tuple[Any, ...] | None) -> _FakeSession:
    session = _FakeSession(row)

    def _factory():
        def _make_session() -> _FakeSession:
            return session

        return _make_session

    monkeypatch.setattr(db_mod, "get_session_factory", _factory)
    return session


@pytest.mark.asyncio
async def test_find_subscription_uses_null_safe_comparison(monkeypatch) -> None:
    session = _install_fake_factory(monkeypatch, row=None)

    await db_mod.find_subscription(
        123,
        country_iso2="tr",
        max_price_uah=None,
        min_stars=None,
        meal_plan=None,
    )

    sql = session.executed_sql
    # Nullable columns must use IS NOT DISTINCT FROM (NULL-safe), not `=`.
    assert "max_price_uah IS NOT DISTINCT FROM :max_price" in sql
    assert "min_stars     IS NOT DISTINCT FROM :stars" in sql
    assert "meal_plan     IS NOT DISTINCT FROM :meal" in sql
    # Country is matched exactly and upper-cased to match how it's stored.
    assert "country_iso2 = :country" in sql
    assert session.executed_params["country"] == "TR"


@pytest.mark.asyncio
async def test_find_subscription_returns_id_when_row_exists(monkeypatch) -> None:
    _install_fake_factory(monkeypatch, row=(77,))

    found = await db_mod.find_subscription(
        123,
        country_iso2="TR",
        max_price_uah=50000,
        min_stars=4,
        meal_plan="AI",
    )

    assert found == 77


@pytest.mark.asyncio
async def test_find_subscription_returns_none_when_no_row(monkeypatch) -> None:
    _install_fake_factory(monkeypatch, row=None)

    found = await db_mod.find_subscription(
        123,
        country_iso2="TR",
        max_price_uah=None,
        min_stars=None,
        meal_plan=None,
    )

    assert found is None
