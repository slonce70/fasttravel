from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.search_service import search_hotels


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def mappings(self):  # type: ignore[no-untyped-def]
        return self

    def all(self) -> list[dict]:
        return self._rows


class _FakeSession:
    def __init__(self) -> None:
        self.scalar_sql = ""
        self.scalar_params: dict = {}
        self.execute_sql = ""
        self.execute_params: dict = {}
        self.rows: list[dict] = []

    async def scalar(self, sql, params):  # type: ignore[no-untyped-def]
        self.scalar_sql = str(sql)
        self.scalar_params = params
        return 0

    async def execute(self, sql, params):  # type: ignore[no-untyped-def]
        self.execute_sql = str(sql)
        self.execute_params = params
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_no_date_meal_search_requires_matching_price_rows() -> None:
    session = _FakeSession()

    await search_hotels(session, country="TR", meal_plan="AI", nights=7)

    assert "JOIN prices px ON px.hotel_id = h.id" in session.scalar_sql
    assert "LEFT JOIN prices px ON px.hotel_id = h.id" not in session.scalar_sql
    assert "meal_plan IN" in session.scalar_sql


@pytest.mark.asyncio
async def test_pax_metadata_is_honest_when_requested_pax_is_not_supported() -> None:
    session = _FakeSession()

    result = await search_hotels(session, adults=3, kids=[7])

    assert result.price_basis_adults == 2
    assert result.price_basis_kids == []
    assert result.pax_supported is False
    assert result.pax_note is not None


@pytest.mark.asyncio
async def test_search_hotels_uses_whitelisted_rating_sort_order() -> None:
    session = _FakeSession()

    await search_hotels(session, sort="rating_desc")

    assert "ORDER BY\n            px.nights_exact    DESC NULLS LAST" in session.execute_sql
    assert "h.review_score     DESC NULLS LAST" in session.execute_sql
    assert "px.effective_price ASC NULLS LAST" in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_uses_whitelisted_name_sort_order() -> None:
    session = _FakeSession()

    await search_hotels(session, sort="name_asc")

    assert "ORDER BY\n            px.nights_exact    DESC NULLS LAST" in session.execute_sql
    assert "h.name_uk          ASC NULLS LAST" in session.execute_sql
    assert "px.effective_price ASC NULLS LAST" in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_filters_by_hotel_name_or_slug_query() -> None:
    session = _FakeSession()

    await search_hotels(session, q="Rixos Premium")

    assert "h.name_uk ILIKE :hotel_query_pattern" in session.execute_sql
    assert "h.name_en ILIKE :hotel_query_pattern" in session.execute_sql
    assert "h.canonical_slug ILIKE :hotel_query_pattern" in session.execute_sql
    assert session.execute_params["hotel_query_pattern"] == "%Rixos Premium%"


@pytest.mark.asyncio
async def test_search_hotels_escapes_wildcards_in_hotel_query() -> None:
    session = _FakeSession()

    await search_hotels(session, q="100%_Resort\\")

    assert session.execute_params["hotel_query_pattern"] == "%100\\%\\_Resort\\\\%"


@pytest.mark.asyncio
async def test_search_hotels_projects_best_deep_link() -> None:
    session = _FakeSession()
    session.rows = [
        {
            "hotel_id": 53769,
            "canonical_slug": "fv-tr-bin-billa-hotel",
            "name_uk": "Bin Billa Hotel",
            "stars": 4,
            "destination_id": 18,
            "min_price_uah": 27401,
            "deep_link": "https://farvater.travel/?q=abc",
            "requested_nights": None,
            "effective_nights": 7,
            "last_observed_at": None,
            "review_score": None,
            "photos": [],
        }
    ]

    result = await search_hotels(session, country="TR")

    assert "FROM current_prices cp" in session.execute_sql
    assert "px.deep_link      AS deep_link" in session.execute_sql
    assert result.items[0].deep_link == "https://farvater.travel/?q=abc"


@pytest.mark.asyncio
async def test_search_hotels_selects_price_nights_and_deep_link_from_one_ranked_offer() -> None:
    session = _FakeSession()

    await search_hotels(session, country="TR", nights=8)

    assert "ranked_prices AS" in session.execute_sql
    assert "ROW_NUMBER() OVER" in session.execute_sql
    assert "(cp.deep_link IS NULL)" not in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_projects_destination_name_and_review_count() -> None:
    """Bot card hides `📍 ...` and `⭐ N відгуків` rows when these fields are
    missing. They were missing because the SQL didn't project them, even
    though both columns exist (destinations.name_uk via JOIN, hotels.review_count
    NOT NULL DEFAULT 0). Regression guard so the projection stays in place."""
    session = _FakeSession()
    session.rows = [
        {
            "hotel_id": 91,
            "canonical_slug": "fv-eg-dana-beach-resort",
            "name_uk": "Albatros Dana Beach Resort",
            "stars": 5,
            "destination_id": 6,
            "destination_name": "Хургада",
            "min_price_uah": 50000,
            "deep_link": "https://farvater.travel/?q=xyz",
            "requested_nights": None,
            "effective_nights": 7,
            "last_observed_at": None,
            "review_score": 9.4,
            "review_count": 1353,
            "photos": [],
        }
    ]

    result = await search_hotels(session, country="EG")

    assert "d.name_uk         AS destination_name" in session.execute_sql
    assert "h.review_count    AS review_count" in session.execute_sql
    item = result.items[0]
    assert item.destination_name == "Хургада"
    assert item.review_count == 1353


@pytest.mark.asyncio
async def test_search_hotels_supports_exact_non_legacy_nights() -> None:
    session = _FakeSession()
    session.rows = [
        {
            "hotel_id": 53769,
            "canonical_slug": "fv-tr-bin-billa-hotel",
            "name_uk": "Bin Billa Hotel",
            "stars": 4,
            "destination_id": 18,
            "min_price_uah": 27401,
            "deep_link": "https://farvater.travel/?q=exact8",
            "requested_nights": 8,
            "effective_nights": 8,
            "last_observed_at": None,
            "review_score": None,
            "photos": [],
        }
    ]

    result = await search_hotels(session, country="TR", nights=8)

    assert "FROM current_prices cp" in session.execute_sql
    assert "cp.nights = CAST(:nights AS INTEGER)" in session.execute_sql
    assert "min_8n" not in session.execute_sql
    assert "BOOL_OR(cp.nights = CAST(:nights AS INTEGER))" in session.execute_sql
    assert "px.nights_exact    DESC NULLS LAST" in session.execute_sql
    assert result.items[0].requested_nights == 8
    assert result.items[0].effective_nights == 8
    assert result.items[0].nights_fallback is False


@pytest.mark.asyncio
async def test_search_hotels_marks_duration_fallback() -> None:
    session = _FakeSession()
    session.rows = [
        {
            "hotel_id": 53769,
            "canonical_slug": "fv-tr-bin-billa-hotel",
            "name_uk": "Bin Billa Hotel",
            "stars": 4,
            "destination_id": 18,
            "min_price_uah": 26000,
            "deep_link": "https://farvater.travel/?q=fallback7",
            "requested_nights": 8,
            "effective_nights": 7,
            "last_observed_at": None,
            "review_score": None,
            "photos": [],
        }
    ]

    result = await search_hotels(session, country="TR", nights=8)

    assert result.items[0].requested_nights == 8
    assert result.items[0].effective_nights == 7
    assert result.items[0].nights_fallback is True


@pytest.mark.asyncio
async def test_search_hotels_uses_between_for_check_in_range() -> None:
    """The bot "when" buckets advertise a window, so they pass
    check_in_min + check_in_max and the price filter must use BETWEEN, not an
    exact-day equality (which matched almost nothing)."""
    session = _FakeSession()

    await search_hotels(
        session,
        country="TR",
        check_in_min=date(2026, 6, 1),
        check_in_max=date(2026, 6, 22),
    )

    assert (
        "cp.check_in BETWEEN CAST(:check_in_min AS DATE) AND CAST(:check_in_max AS DATE)"
        in session.execute_sql
    )
    # Range mode must not also pin an exact day.
    assert "cp.check_in = CAST(:check_in AS DATE)" not in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_exact_check_in_takes_precedence_over_range() -> None:
    """The web date-picker path (exact check_in) is preserved and wins over a
    range if both are somehow supplied — backward compatibility."""
    session = _FakeSession()

    await search_hotels(
        session,
        country="TR",
        check_in=date(2026, 6, 15),
        check_in_min=date(2026, 6, 1),
        check_in_max=date(2026, 6, 22),
    )

    assert "cp.check_in = CAST(:check_in AS DATE)" in session.execute_sql
    assert "BETWEEN" not in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_no_date_filter_when_range_incomplete() -> None:
    """A lone check_in_min (no max) does not emit a date filter at the service
    layer — the router collapses that legacy case to an exact check_in before
    calling, so the service only sees a complete range or nothing."""
    session = _FakeSession()

    await search_hotels(session, country="TR", check_in_min=date(2026, 6, 1))

    assert "BETWEEN" not in session.execute_sql
    assert "cp.check_in = CAST(:check_in AS DATE)" not in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_matches_only_departures_inside_window(
    db_session: AsyncSession,
) -> None:
    """End-to-end range filter: a hotel with a departure inside the window is
    returned at that price; one only outside the window is excluded."""
    suffix = uuid4().hex[:10]
    operator_id = await db_session.scalar(
        text(
            """
            INSERT INTO operators (code, display_name)
            VALUES (:code, 'Range Window Operator')
            RETURNING id
            """
        ),
        {"code": f"range-window-{suffix}"},
    )
    country_iso2 = "ZY"
    destination_id = await db_session.scalar(
        text(
            """
            INSERT INTO destinations (country_iso2, region_slug, name_uk)
            VALUES (:country_iso2, :slug, 'Range Window Destination')
            RETURNING id
            """
        ),
        {"country_iso2": country_iso2, "slug": f"range-window-{suffix}"},
    )
    in_window_hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, destination_id, is_active, has_active_prices
            )
            VALUES (:slug, 'In Window Hotel', :destination_id, TRUE, TRUE)
            RETURNING id
            """
        ),
        {"slug": f"fv-zy-in-window-{suffix}", "destination_id": destination_id},
    )
    out_window_hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, destination_id, is_active, has_active_prices
            )
            VALUES (:slug, 'Out Of Window Hotel', :destination_id, TRUE, TRUE)
            RETURNING id
            """
        ),
        {"slug": f"fv-zy-out-window-{suffix}", "destination_id": destination_id},
    )
    assert isinstance(operator_id, int)
    assert isinstance(in_window_hotel_id, int)
    assert isinstance(out_window_hotel_id, int)

    today = date.today()
    check_in_min = today + timedelta(days=10)
    check_in_max = today + timedelta(days=20)
    inside = today + timedelta(days=15)
    outside = today + timedelta(days=40)
    observed_at = datetime.now(UTC)
    await db_session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                :observed_at, :hotel_id, :operator_id, :check_in, :nights, :meal_plan,
                :room_category, :price_uah, 'UAH', :deep_link
            )
            """
        ),
        [
            {
                "observed_at": observed_at,
                "hotel_id": in_window_hotel_id,
                "operator_id": operator_id,
                "check_in": inside,
                "nights": 7,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 33000,
                "deep_link": f"https://example.test/{suffix}/inside",
            },
            {
                "observed_at": observed_at,
                "hotel_id": out_window_hotel_id,
                "operator_id": operator_id,
                "check_in": outside,
                "nights": 7,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 29000,
                "deep_link": f"https://example.test/{suffix}/outside",
            },
        ],
    )
    await db_session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))

    result = await search_hotels(
        db_session,
        country=country_iso2,
        check_in_min=check_in_min,
        check_in_max=check_in_max,
        limit=20,
    )
    found_ids = {item.hotel_id for item in result.items}

    assert in_window_hotel_id in found_ids
    assert out_window_hotel_id not in found_ids
    in_window = next(i for i in result.items if i.hotel_id == in_window_hotel_id)
    assert in_window.min_price_uah == 33000


@pytest.mark.asyncio
async def test_search_hotels_falls_back_to_price_sort_for_unknown_sort() -> None:
    session = _FakeSession()

    await search_hotels(session, sort="h.name_uk; DROP TABLE hotels")

    assert "ORDER BY\n            px.nights_exact    DESC NULLS LAST" in session.execute_sql
    assert "px.effective_price ASC NULLS LAST" in session.execute_sql


@pytest.mark.asyncio
async def test_search_hotels_selects_coherent_offer_row_from_current_prices(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    operator_id = await db_session.scalar(
        text(
            """
            INSERT INTO operators (code, display_name)
            VALUES (:code, 'Search Coherence Operator')
            RETURNING id
            """
        ),
        {"code": f"search-coherence-{suffix}"},
    )
    country_iso2 = "ZZ"
    destination_id = await db_session.scalar(
        text(
            """
            INSERT INTO destinations (country_iso2, region_slug, name_uk)
            VALUES (:country_iso2, :slug, 'Search Coherence Destination')
            RETURNING id
            """
        ),
        {"country_iso2": country_iso2, "slug": f"search-coherence-{suffix}"},
    )
    exact_hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, destination_id, is_active, has_active_prices
            )
            VALUES (:slug, 'Exact Coherence Hotel', :destination_id, TRUE, TRUE)
            RETURNING id
            """
        ),
        {"slug": f"fv-tr-exact-coherence-{suffix}", "destination_id": destination_id},
    )
    fallback_hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, destination_id, is_active, has_active_prices
            )
            VALUES (:slug, 'Fallback Coherence Hotel', :destination_id, TRUE, TRUE)
            RETURNING id
            """
        ),
        {"slug": f"fv-tr-fallback-coherence-{suffix}", "destination_id": destination_id},
    )
    assert isinstance(operator_id, int)
    assert isinstance(exact_hotel_id, int)
    assert isinstance(fallback_hotel_id, int)

    check_in = date.today() + timedelta(days=30)
    observed_at = datetime.now(UTC)
    await db_session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                :observed_at, :hotel_id, :operator_id, :check_in, :nights, :meal_plan,
                :room_category, :price_uah, 'UAH', :deep_link
            )
            """
        ),
        [
            {
                "observed_at": observed_at,
                "hotel_id": exact_hotel_id,
                "operator_id": operator_id,
                "check_in": check_in,
                "nights": 7,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 30000,
                "deep_link": f"https://example.test/{suffix}/fallback-cheaper",
            },
            {
                "observed_at": observed_at,
                "hotel_id": exact_hotel_id,
                "operator_id": operator_id,
                "check_in": check_in,
                "nights": 8,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 50000,
                "deep_link": f"https://example.test/{suffix}/exact8",
            },
            {
                "observed_at": observed_at,
                "hotel_id": fallback_hotel_id,
                "operator_id": operator_id,
                "check_in": check_in,
                "nights": 7,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 26000,
                "deep_link": None,
            },
            {
                "observed_at": observed_at,
                "hotel_id": fallback_hotel_id,
                "operator_id": operator_id,
                "check_in": check_in,
                "nights": 10,
                "meal_plan": "AI",
                "room_category": "Standard",
                "price_uah": 31000,
                "deep_link": f"https://example.test/{suffix}/fallback-link-pricier",
            },
        ],
    )
    await db_session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))

    result = await search_hotels(
        db_session,
        country=country_iso2,
        check_in=check_in,
        nights=8,
        meal_plan="AI",
        limit=20,
    )
    by_id = {item.hotel_id: item for item in result.items}

    exact = by_id[exact_hotel_id]
    assert exact.min_price_uah == 50000
    assert exact.effective_nights == 8
    assert exact.deep_link == f"https://example.test/{suffix}/exact8"
    assert exact.nights_fallback is False

    fallback = by_id[fallback_hotel_id]
    assert fallback.min_price_uah == 26000
    assert fallback.effective_nights == 7
    assert fallback.deep_link is None
    assert fallback.nights_fallback is True
