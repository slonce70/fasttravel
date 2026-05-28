from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.deal_detection import DATE_DIP_POLICY
from src.routers import hotels as hotels_router
from src.services.calendar_service import get_calendar


@pytest.mark.asyncio
async def test_calendar_route_passes_meal_plan_filter(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_get_calendar(
        session: AsyncSession,
        hotel_id: int,
        from_date: date,
        to_date: date,
        meal_plan: str | None = None,
        nights: int | None = None,
    ) -> list[object]:
        captured.update(
            {
                "session": session,
                "hotel_id": hotel_id,
                "from_date": from_date,
                "to_date": to_date,
                "meal_plan": meal_plan,
                "nights": nights,
            }
        )
        return []

    monkeypatch.setattr(hotels_router, "get_calendar", fake_get_calendar)

    response = await client.get(
        "/api/hotels/42/calendar?from=2026-05-25&to=2026-06-05&meal_plan=AI&nights=5"
    )

    assert response.status_code == 200
    assert captured["session"] is db_session
    assert captured["hotel_id"] == 42
    assert captured["from_date"] == date(2026, 5, 25)
    assert captured["to_date"] == date(2026, 6, 5)
    assert captured["meal_plan"] == "AI"
    assert captured["nights"] == 5


class _FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeCalendarSession:
    """Mock session that records the SQL it sees and returns a single
    fixed CalendarDay-shaped row so we can assert the service layer's
    query construction and decoding."""

    def __init__(self, prices_by_night: dict[str, int] | None = None) -> None:
        self.statement = ""
        self.params: dict[str, object] = {}
        self._prices = prices_by_night or {"5": 55555}

    async def execute(self, statement, params):  # type: ignore[no-untyped-def]
        self.statement = str(statement)
        self.params = dict(params)
        return _FakeResult(
            [
                {
                    "check_in": date(2026, 5, 27),
                    "meal_plan": self.params.get("requested_meal_plan"),
                    "min_price_uah": min(self._prices.values()),
                    "prices_by_night": dict(self._prices),
                    "observed_at": None,
                    "date_dip_price_uah": None,
                    "date_dip_baseline_uah": None,
                    "date_dip_discount_pct": None,
                    "date_dip_sample_n": None,
                }
            ]
        )


@pytest.mark.asyncio
async def test_calendar_service_filters_exact_nights_from_current_prices() -> None:
    session = _FakeCalendarSession({"5": 55555})

    rows = await get_calendar(
        session, 54034, date(2026, 5, 24), date(2026, 6, 1), meal_plan="AI", nights=5
    )

    assert "FROM current_prices cp" in session.statement
    assert "cp.nights = :nights" in session.statement
    # Exact-nights branch builds prices_by_night via jsonb_build_object so
    # the response shape is identical with or without ?nights.
    assert "jsonb_build_object" in session.statement
    assert session.params["nights"] == 5
    assert session.params["nights_key"] == "5"
    assert session.params["meal_codes"] == ["AI"]
    assert rows[0].min_price_uah == 55555
    assert rows[0].prices_by_night == {"5": 55555}
    assert rows[0].meal_plan == "AI"


@pytest.mark.asyncio
async def test_calendar_service_exact_nights_annotations_use_detector_scope() -> None:
    session = _FakeCalendarSession({"7": 100000})

    rows = await get_calendar(
        session, 54034, date(2026, 6, 1), date(2026, 6, 30), meal_plan="AI", nights=7
    )

    assert "ROW_NUMBER() OVER" in session.statement
    assert "PARTITION BY cp.check_in" in session.statement
    assert "best_date_dip AS" in session.statement
    assert "neighbor.operator_id = cp.operator_id" in session.statement
    assert "neighbor.nights = cp.nights" in session.statement
    assert "neighbor.meal_plan = cp.meal_plan" in session.statement
    assert "neighbor.room_family = cp.room_family" in session.statement
    assert "GROUP BY neighbor.check_in" in session.statement
    assert (
        "neighbor.check_in BETWEEN "
        f"cp.check_in - INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'" in session.statement
    )
    assert (
        f"AND cp.check_in + INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'"
        in session.statement
    )
    assert f"hs.sample_n >= {DATE_DIP_POLICY.min_sample_size}" in session.statement
    assert f"hs.p_max <= hs.p_min * {DATE_DIP_POLICY.max_spread_ratio_sql}" in session.statement
    assert (
        "cp.check_in BETWEEN "
        f"CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_start_days} days'"
        in session.statement
    )
    assert (
        f"AND CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_end_days} days'"
        in session.statement
    )
    assert f"cp.price_uah < hs.p50 * {DATE_DIP_POLICY.discount_multiplier_sql}" in session.statement
    assert (
        f"hs.p50 - cp.price_uah >= {DATE_DIP_POLICY.min_absolute_saving_uah}" in session.statement
    )
    assert rows[0].date_dip_discount_pct is None


@pytest.mark.asyncio
async def test_calendar_service_exact_nights_date_dip_annotations_require_comparable_rows(
    db_session: AsyncSession,
) -> None:
    operator_id = await db_session.scalar(
        text(
            """
            INSERT INTO operators (code, display_name)
            VALUES ('calendar-scope-main', 'Calendar Scope Main')
            RETURNING id
            """
        )
    )
    other_operator_id = await db_session.scalar(
        text(
            """
            INSERT INTO operators (code, display_name)
            VALUES ('calendar-scope-other', 'Calendar Scope Other')
            RETURNING id
            """
        )
    )
    hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (canonical_slug, name_uk, is_active)
            VALUES ('calendar-scope-hotel', 'Calendar Scope Hotel', TRUE)
            RETURNING id
            """
        )
    )
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))
    assert isinstance(operator_id, int)
    assert isinstance(other_operator_id, int)
    assert isinstance(hotel_id, int)
    assert isinstance(db_today, date)
    assert db_now is not None
    old_observed_at = db_now - timedelta(days=1)

    def price_row(
        day_offset: int,
        room_category: str,
        price_uah: int,
        slug: str,
        *,
        operator: int = operator_id,
        observed_at=db_now,
    ) -> dict[str, object]:
        return {
            "observed_at": observed_at,
            "hotel_id": hotel_id,
            "operator_id": operator,
            "check_in": db_today + timedelta(days=day_offset),
            "room_category": room_category,
            "price_uah": price_uah,
            "deep_link": f"https://example.test/{slug}",
        }

    await db_session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                :observed_at, :hotel_id, :operator_id, :check_in, 7, 'AI',
                :room_category, :price_uah, 'UAH', :deep_link
            )
            """
        ),
        [
            # Valid dip, but inside the scheduler's 0..4 day exclusion window.
            price_row(1, "Villa", 50000, "early-target"),
            price_row(2, "Villa", 60000, "early-neighbor-1"),
            price_row(3, "Villa", 62000, "early-neighbor-2"),
            price_row(4, "Villa", 64000, "early-neighbor-3"),
            price_row(5, "Villa", 66000, "early-neighbor-4"),
            # Normal positive marker; a newer, pricier row on the same day
            # proves observed_at reports day freshness, not the min row age.
            price_row(10, "Standard Room", 100000, "target", observed_at=old_observed_at),
            price_row(10, "Suite", 130000, "newer-pricier-same-day"),
            price_row(11, "Double Standard", 103000, "neighbor-1"),
            price_row(12, "Standard DBL", 105000, "neighbor-2"),
            price_row(13, "Standard Room", 106000, "neighbor-3"),
            price_row(14, "Double Standard", 108000, "neighbor-4"),
            # Same hotel/date/nights/meal, but only a different operator has
            # the cheap target; the main operator's expensive neighbors must
            # not create a false marker for that other operator.
            price_row(
                35,
                "Standard Room",
                100000,
                "other-target",
                operator=other_operator_id,
            ),
            price_row(36, "Standard Room", 160000, "mismatch-1"),
            price_row(37, "Double Standard", 165000, "mismatch-2"),
            price_row(38, "Standard DBL", 166000, "mismatch-3"),
            price_row(39, "Standard Room", 168000, "mismatch-4"),
            # Exact 4.00% is not enough: scheduler uses strict < 0.96.
            price_row(50, "Family Room", 96000, "boundary-target"),
            price_row(51, "Family Room", 99000, "boundary-neighbor-1"),
            price_row(52, "Family Room", 100000, "boundary-neighbor-2"),
            price_row(53, "Family Room", 100000, "boundary-neighbor-3"),
            price_row(54, "Family Room", 101000, "boundary-neighbor-4"),
            # The cheapest row is not anomalous, but the suite row is a real
            # production date-dip. Calendar should still mark the day.
            price_row(70, "Standard Room", 100000, "flat-min-row"),
            price_row(70, "Suite", 120000, "suite-target"),
            price_row(71, "Standard Room", 100000, "flat-neighbor-1"),
            price_row(72, "Standard Room", 101000, "flat-neighbor-2"),
            price_row(73, "Standard Room", 102000, "flat-neighbor-3"),
            price_row(74, "Standard Room", 103000, "flat-neighbor-4"),
            price_row(71, "Junior Suite", 150000, "suite-neighbor-1"),
            price_row(72, "Junior Suite", 151000, "suite-neighbor-2"),
            price_row(73, "Junior Suite", 152000, "suite-neighbor-3"),
            price_row(74, "Junior Suite", 153000, "suite-neighbor-4"),
            # One neighboring date with four aliases is still one calendar
            # comparison point. It must not satisfy the min-sample gate by
            # counting raw room labels as independent nearby dates.
            price_row(
                80,
                "Standard Room",
                100000,
                "alias-inflation-target",
                operator=other_operator_id,
            ),
            price_row(
                81,
                "Standard Room",
                120000,
                "alias-inflation-neighbor-1",
                operator=other_operator_id,
            ),
            price_row(
                81,
                "Standard DBL",
                121000,
                "alias-inflation-neighbor-2",
                operator=other_operator_id,
            ),
            price_row(
                81,
                "Double Standard",
                122000,
                "alias-inflation-neighbor-3",
                operator=other_operator_id,
            ),
            price_row(
                81,
                "STD",
                123000,
                "alias-inflation-neighbor-4",
                operator=other_operator_id,
            ),
        ],
    )
    await db_session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))

    rows = await get_calendar(
        db_session,
        hotel_id,
        db_today + timedelta(days=1),
        db_today + timedelta(days=81),
        meal_plan="AI",
        nights=7,
    )
    by_date = {row.check_in: row for row in rows}

    early = by_date[db_today + timedelta(days=1)]
    assert early.date_dip_price_uah is None
    assert early.date_dip_baseline_uah is None
    assert early.date_dip_discount_pct is None

    positive = by_date[db_today + timedelta(days=10)]
    assert positive.min_price_uah == 100000
    assert positive.observed_at == db_now
    assert positive.date_dip_price_uah == 100000
    assert positive.date_dip_baseline_uah == 105500
    assert positive.date_dip_discount_pct == 5.21
    assert positive.date_dip_sample_n == 4

    mismatched_operator = by_date[db_today + timedelta(days=35)]
    assert mismatched_operator.date_dip_price_uah is None
    assert mismatched_operator.date_dip_baseline_uah is None
    assert mismatched_operator.date_dip_discount_pct is None
    assert mismatched_operator.date_dip_sample_n is None

    exact_boundary = by_date[db_today + timedelta(days=50)]
    assert exact_boundary.date_dip_price_uah is None
    assert exact_boundary.date_dip_baseline_uah is None
    assert exact_boundary.date_dip_discount_pct is None

    suite_candidate = by_date[db_today + timedelta(days=70)]
    assert suite_candidate.min_price_uah == 100000
    assert suite_candidate.date_dip_price_uah == 120000
    assert suite_candidate.date_dip_baseline_uah == 151500
    assert suite_candidate.date_dip_discount_pct == 20.79
    assert suite_candidate.date_dip_sample_n == 4

    alias_inflation = by_date[db_today + timedelta(days=80)]
    assert alias_inflation.date_dip_price_uah is None
    assert alias_inflation.date_dip_baseline_uah is None
    assert alias_inflation.date_dip_discount_pct is None
    assert alias_inflation.date_dip_sample_n is None


@pytest.mark.asyncio
async def test_calendar_service_echoes_meal_filter_without_exact_nights() -> None:
    session = _FakeCalendarSession({"7": 44444, "8": 45555})

    rows = await get_calendar(session, 54034, date(2026, 5, 24), date(2026, 6, 1), meal_plan="AI")

    assert "FROM hotel_calendar_prices" in session.statement
    assert session.params["meal_codes"] == ["AI"]
    assert session.params["requested_meal_plan"] == "AI"
    assert rows[0].meal_plan == "AI"


@pytest.mark.asyncio
async def test_calendar_service_returns_prices_by_night_for_non_legacy_nights() -> None:
    """Regression for Stage 2 audit fix: ?nights=9 used to fall back to
    min_price_uah because the MV only exposed 7/10/14. After migration 016
    we return the per-nights map for any value scrape supplies (7..14)."""
    session = _FakeCalendarSession({"9": 49000})

    rows = await get_calendar(session, 42, date(2026, 5, 24), date(2026, 6, 1), nights=9)

    assert session.params["nights"] == 9
    assert session.params["nights_key"] == "9"
    assert rows[0].prices_by_night == {"9": 49000}
    assert rows[0].min_price_uah == 49000


@pytest.mark.asyncio
async def test_calendar_service_reads_mv_when_no_nights() -> None:
    """Without ?nights= the service must read hotel_calendar_prices
    (the MV that already stores the full prices_by_night map)."""
    session = _FakeCalendarSession({"7": 50000, "8": 51000, "14": 47000})

    rows = await get_calendar(session, 42, date(2026, 5, 24), date(2026, 6, 1))

    assert "FROM hotel_calendar_prices" in session.statement
    assert "jsonb_each_text" in session.statement
    assert rows[0].prices_by_night == {"7": 50000, "8": 51000, "14": 47000}


@pytest.mark.asyncio
async def test_hotel_route_resolves_slug_alias_to_canonical_hotel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO hotels (id, canonical_slug, name_uk, is_active)
            VALUES (990001, 'test-canonical-alias-hotel', 'Alias Test Hotel', TRUE)
            """
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
            VALUES ('test-old-alias-hotel', 990001, 'test duplicate')
            """
        )
    )

    response = await client.get("/api/hotels/test-old-alias-hotel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 990001
    assert payload["canonical_slug"] == "test-canonical-alias-hotel"


@pytest.mark.asyncio
async def test_hotel_route_returns_404_for_unknown_slug(client: AsyncClient) -> None:
    response = await client.get("/api/hotels/not-a-real-hotel-slug")

    assert response.status_code == 404
