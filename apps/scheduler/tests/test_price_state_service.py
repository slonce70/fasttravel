from __future__ import annotations

from src.services.price_state import decay_active_prices, mark_priced, mark_unpriced


class _FakeResult:
    rowcount = 4


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, sql, params):  # type: ignore[no-untyped-def]
        self.calls.append((str(sql), params))
        return _FakeResult()


async def test_mark_priced_stamps_active_price_state() -> None:
    db = _FakeSession()

    await mark_priced(db, 123)

    statement, params = db.calls[0]
    assert "has_active_prices = TRUE" in statement
    assert "last_priced_at = NOW()" in statement
    assert params == {"id": 123}


async def test_mark_unpriced_stamps_completed_probe_without_inventory() -> None:
    db = _FakeSession()

    await mark_unpriced(db, 123)

    statement, params = db.calls[0]
    assert "has_active_prices = FALSE" in statement
    assert "last_priced_at = NOW()" in statement
    assert params == {"id": 123}


async def test_decay_active_prices_demotes_stale_active_hotels() -> None:
    db = _FakeSession()

    demoted = await decay_active_prices(db, stale_after_days=3)

    statement, params = db.calls[0]
    assert demoted == 4
    assert "has_active_prices = FALSE" in statement
    assert "make_interval(days => :d)" in statement
    assert params == {"d": 3}
