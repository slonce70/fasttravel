from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from shared.deal_detection import DATE_DIP_POLICY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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

    # The calendar shares the channel detector's regime-local V CTE, scoped to
    # this hotel — so the marked dates are exactly the dates that would publish.
    assert "series AS" in session.statement
    assert "framed AS" in session.statement
    assert "local_stats AS" in session.statement
    assert "best_date_dip AS" in session.statement
    assert "AND cp.hotel_id = :hotel_id" in session.statement
    assert "RANGE BETWEEN INTERVAL '7 days' PRECEDING" in session.statement
    assert "INTERVAL '7 days' FOLLOWING" in session.statement
    # Two-sided V-bottom + return-to-baseline guards.
    assert "f.price_uah < f.prec_min" in session.statement
    assert "f.price_uah < f.foll_min" in session.statement
    assert (
        "GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) * "
        f"{DATE_DIP_POLICY.side_match_ratio_sql}" in session.statement
    )
    # Same-room casing collapse + magnitude gates applied per nights.
    assert "lower(btrim(cp.room_category))" in session.statement
    assert "ls.nights = :nights" in session.statement
    assert f"ls.discount_pct >= {DATE_DIP_POLICY.dip_threshold_pct_sql}" in session.statement
    assert f"ls.discount_pct <= {DATE_DIP_POLICY.max_depth_pct_sql}" in session.statement
    assert (
        f"(ls.baseline_p50 - ls.price_uah) >= {DATE_DIP_POLICY.min_absolute_saving_uah}"
        in session.statement
    )
    assert (
        "CURRENT_DATE + INTERVAL "
        f"'{DATE_DIP_POLICY.lookahead_start_days} days'" in session.statement
    )
    # The old trimmed-mean / percentile-rank machinery is gone.
    assert "trimmed_mean" not in session.statement
    assert "PERCENT_RANK" not in session.statement
    assert "neighbor.operator_id" not in session.statement
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
            # A genuine regime-local V-bottom at +27 (85000) inside a flat
            # 100000 Standard run: matching shoulders on both sides -> marked.
            *[price_row(o, "Standard Room", 100000, f"flat-{o}") for o in range(20, 35) if o != 27],
            price_row(27, "Standard Room", 85000, "v-dip-target"),
            # Operator scoping: only the OTHER operator has the cheap +53 target;
            # the main operator's pricey same-window dates must not mark it,
            # and the other operator has no same-operator shoulders of its own.
            price_row(53, "Standard Room", 80000, "other-op-target", operator=other_operator_id),
            *[price_row(o, "Standard Room", 150000, f"main-expensive-{o}") for o in range(49, 59)],
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

    # The genuine V-bottom is annotated with the local-typical (matched-side
    # average) baseline — the same definition the channel detector publishes.
    dip = by_date[db_today + timedelta(days=27)]
    assert dip.date_dip_price_uah == 85000
    assert dip.date_dip_baseline_uah == 100000
    assert dip.date_dip_discount_pct == 15.0
    assert dip.date_dip_sample_n is not None and dip.date_dip_sample_n >= 6

    # A flat neighbouring date is not a dip (it isn't below its own shoulders).
    flat = by_date[db_today + timedelta(days=25)]
    assert flat.date_dip_price_uah is None
    assert flat.date_dip_baseline_uah is None
    assert flat.date_dip_discount_pct is None

    # Operator scoping: the other operator's cheap +53 has no same-operator
    # shoulders, so the main operator's pricey dates can't mark it.
    other_operator_day = by_date[db_today + timedelta(days=53)]
    assert other_operator_day.date_dip_discount_pct is None
    assert other_operator_day.date_dip_sample_n is None


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
