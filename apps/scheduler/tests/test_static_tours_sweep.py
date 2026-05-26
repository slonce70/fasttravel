"""Unit tests for static_tours_sweep.

The sweep is the hot promo-ingest job — it's what writes into the
promo_offers table that detect_deals (Sprint 1D) will then convert to
bucket-based deals. These tests stub out the HTTP client + DB so they
run without the docker stack.
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.clients.static_tours import PromoTourRow

# `import src.jobs.static_tours_sweep as sweep` resolves to the FUNCTION
# (jobs/__init__ re-exports it as the same name), shadowing the
# submodule. Use importlib to get the actual module object so
# monkeypatch can target module-level globals.
sweep = importlib.import_module("src.jobs.static_tours_sweep")


@pytest.fixture(autouse=True)
def _enable_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """All tests run with the flag ON unless explicitly cleared."""
    monkeypatch.setenv(sweep.FEATURE_FLAG_ENV, "1")


def _row(
    *,
    hotel_key: int = 15937,
    system_key: str = "sk-1",
    bucket: str = "gorjashhie-tury",
    is_hot: bool = True,
) -> PromoTourRow:
    return PromoTourRow(
        bucket_slug=bucket,
        hotel_key=hotel_key,
        system_key=system_key,
        check_in=date(2026, 7, 1),
        nights=7,
        meal_plan="AI",
        price_uah=29847,
        red_price_uah=29847,
        is_hot=is_hot,
        is_early=False,
        is_best_deal=False,
        is_recommended=True,
        is_choice_farvater=False,
        is_otp=True,
        is_last_seats=False,
        is_black_friday=False,
        is_vip=False,
        hot_type="1",
        early_type=None,
        operator_name="Alliance",
        operator_id_int=119,
        promotion_end_date=None,
        loaded_date=datetime(2026, 5, 24, 22, 56, tzinfo=UTC),
        raw={"hotelKey": str(hotel_key), "SystemKey": system_key, "isHot": is_hot},
    )


# ── feature flag ────────────────────────────────────────────────────────


async def test_skips_when_feature_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default off — calling the job must no-op without touching DB/Redis."""
    monkeypatch.delenv(sweep.FEATURE_FLAG_ENV, raising=False)
    result = await sweep.static_tours_sweep()
    assert result == 0


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
async def test_skips_for_falsy_flag_values(val: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sweep.FEATURE_FLAG_ENV, val)
    result = await sweep.static_tours_sweep()
    assert result == 0


# ── happy path ──────────────────────────────────────────────────────────


async def test_happy_path_inserts_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """One bucket, two tours, both hotels resolved → both rows insert."""

    tours = [_row(hotel_key=1, system_key="sk-a"), _row(hotel_key=2, system_key="sk-b")]

    # Patch _farvater_operator_id → return a valid operator id without DB
    monkeypatch.setattr(sweep, "_farvater_operator_id", AsyncMock(return_value=42))
    # Patch hotel-id resolution → both keys known
    monkeypatch.setattr(
        sweep,
        "_resolve_hotel_ids",
        AsyncMock(return_value={1: 1001, 2: 1002}),
    )
    insert_mock = AsyncMock(return_value=2)
    monkeypatch.setattr(sweep, "_upsert_promo_offers", insert_mock)
    monkeypatch.setattr(sweep, "_record_sweep_run", AsyncMock())

    # Stub async_session_factory with a no-op context manager so the
    # `async with async_session_factory() as db: ...` blocks work.
    class _NullSession:
        async def __aenter__(self):
            return MagicMock(commit=AsyncMock())

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "async_session_factory", lambda: _NullSession())
    monkeypatch.setattr(sweep, "get_redis", AsyncMock(return_value=MagicMock()))

    # Patch the HTTP client open + fetch to return our pre-baked tours.
    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "FarvaterProdClient", lambda _r: _FakeClient())
    monkeypatch.setattr(sweep, "fetch_bucket_all_pages", AsyncMock(return_value=tours))

    result = await sweep.static_tours_sweep(
        sweep_matrix=(("gorjashhie-tury", -1),),
    )
    assert result == 2
    # _upsert_promo_offers was called with both tours
    assert insert_mock.await_count == 1
    call_kwargs = insert_mock.await_args.kwargs
    assert len(call_kwargs["tours"]) == 2


async def test_records_no_operator_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If `farvater` operator row is missing → log + return 0 cleanly."""
    monkeypatch.setattr(sweep, "_farvater_operator_id", AsyncMock(return_value=None))

    class _NullSession:
        async def __aenter__(self):
            return MagicMock(commit=AsyncMock())

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "async_session_factory", lambda: _NullSession())

    result = await sweep.static_tours_sweep()
    assert result == 0


async def test_unresolved_hotel_keys_are_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tours whose hotelKey isn't in hotel_operator_mapping get dropped
    (they'll be picked up next sitemap pass); the sweep doesn't fail."""
    tours = [_row(hotel_key=1, system_key="sk-a"), _row(hotel_key=99, system_key="sk-b")]

    monkeypatch.setattr(sweep, "_farvater_operator_id", AsyncMock(return_value=42))
    # Only key=1 resolves; key=99 is unknown
    monkeypatch.setattr(sweep, "_resolve_hotel_ids", AsyncMock(return_value={1: 1001}))
    insert_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(sweep, "_upsert_promo_offers", insert_mock)
    monkeypatch.setattr(sweep, "_record_sweep_run", AsyncMock())

    class _NullSession:
        async def __aenter__(self):
            return MagicMock(commit=AsyncMock())

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "async_session_factory", lambda: _NullSession())
    monkeypatch.setattr(sweep, "get_redis", AsyncMock(return_value=MagicMock()))

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "FarvaterProdClient", lambda _r: _FakeClient())
    monkeypatch.setattr(sweep, "fetch_bucket_all_pages", AsyncMock(return_value=tours))

    result = await sweep.static_tours_sweep(
        sweep_matrix=(("gorjashhie-tury", -1),),
    )
    # Returned upsert mock count is 1 (we configured it). The behaviour
    # under test is that unresolved keys don't make the sweep raise.
    assert result == 1


# ── breaker / cap stop iteration ────────────────────────────────────────


async def test_breaker_open_aborts_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the breaker fires mid-sweep, the rest of the matrix is skipped
    AND a `partial`/`failed` row is recorded — not silently lost."""
    monkeypatch.setattr(sweep, "_farvater_operator_id", AsyncMock(return_value=42))
    record_mock = AsyncMock()
    monkeypatch.setattr(sweep, "_record_sweep_run", record_mock)

    class _NullSession:
        async def __aenter__(self):
            return MagicMock(commit=AsyncMock())

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "async_session_factory", lambda: _NullSession())
    monkeypatch.setattr(sweep, "get_redis", AsyncMock(return_value=MagicMock()))

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "FarvaterProdClient", lambda _r: _FakeClient())
    monkeypatch.setattr(
        sweep,
        "fetch_bucket_all_pages",
        AsyncMock(side_effect=sweep.BreakerOpen("open for 3600s")),
    )

    result = await sweep.static_tours_sweep(
        sweep_matrix=(
            ("gorjashhie-tury", -1),
            ("rannee-bronirovanie", -1),
        ),
    )
    assert result == 0
    record_mock.assert_awaited_once()
    args = record_mock.await_args.kwargs
    assert args["status"] == "partial"
    assert "BreakerOpen" in args["error"]


async def test_one_bucket_429_continues_with_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single 429 on one (bucket, country) should not stop the others."""
    monkeypatch.setattr(sweep, "_farvater_operator_id", AsyncMock(return_value=42))
    monkeypatch.setattr(sweep, "_resolve_hotel_ids", AsyncMock(return_value={1: 1001}))
    monkeypatch.setattr(sweep, "_upsert_promo_offers", AsyncMock(return_value=1))
    record_mock = AsyncMock()
    monkeypatch.setattr(sweep, "_record_sweep_run", record_mock)

    class _NullSession:
        async def __aenter__(self):
            return MagicMock(commit=AsyncMock())

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "async_session_factory", lambda: _NullSession())
    monkeypatch.setattr(sweep, "get_redis", AsyncMock(return_value=MagicMock()))

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sweep, "FarvaterProdClient", lambda _r: _FakeClient())

    call_count = {"n": 0}

    async def _fetch(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise sweep.UpstreamRateLimited("429")
        return [_row(hotel_key=1, system_key=f"sk-{call_count['n']}")]

    monkeypatch.setattr(sweep, "fetch_bucket_all_pages", AsyncMock(side_effect=_fetch))

    result = await sweep.static_tours_sweep(
        sweep_matrix=(
            ("gorjashhie-tury", -1),
            ("rannee-bronirovanie", -1),
        ),
    )
    # First bucket 429'd → 0 inserts; second bucket succeeded → 1 insert.
    assert result == 1
    args = record_mock.await_args.kwargs
    assert args["status"] == "partial"
    assert "429" in args["error"]
