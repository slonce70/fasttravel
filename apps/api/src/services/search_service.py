"""Hotel search service.

Reads `current_prices` MV so search results carry a real offer price,
the matching Farvater deep link, and exact/fallback nights metadata.

Two query regimes:

  1. `nights` given → choose the exact-night offer per hotel first;
     if a hotel has no exact-night offer, fall back to its cheapest
     current offer and mark `nights_fallback=true`.

  2. `nights` omitted → choose the cheapest current offer per hotel.

Exact-night hotels are ranked before fallback hotels globally. That
keeps search honest: fallback rows are visible, but they do not outrank
real matches for the requested duration.

ORDER BY is whitelist-driven across both regimes. Unknown values fall back to
price ascending so URL input can never become arbitrary SQL.

We hand-write SQL (text()) rather than going through SQLAlchemy ORM
because the MV isn't mapped (intentional — it's storage, not domain).
Mirrors the pattern in `calendar_service.get_calendar`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.search import PaginatedSearchResults, SearchResultItem
from src.services.meal_normalizer import raw_codes_for

_SORT_ORDER_BY = {
    "price_asc": """\
            px.nights_exact    DESC NULLS LAST,
            px.effective_price ASC NULLS LAST,
            h.review_score     DESC NULLS LAST,
            h.id               ASC
    """,
    "price_desc": """\
            px.nights_exact    DESC NULLS LAST,
            px.effective_price DESC NULLS LAST,
            h.review_score     DESC NULLS LAST,
            h.id               ASC
    """,
    "rating_desc": """\
            px.nights_exact    DESC NULLS LAST,
            h.review_score     DESC NULLS LAST,
            px.effective_price ASC NULLS LAST,
            h.id               ASC
    """,
    "name_asc": """\
            px.nights_exact    DESC NULLS LAST,
            h.name_uk          ASC NULLS LAST,
            px.effective_price ASC NULLS LAST,
            h.id               ASC
    """,
    "stars_desc": """\
            px.nights_exact    DESC NULLS LAST,
            h.stars            DESC NULLS LAST,
            h.review_score     DESC NULLS LAST,
            px.effective_price ASC NULLS LAST,
            h.id               ASC
    """,
}


async def search_hotels(
    session: AsyncSession,
    *,
    country: str | None = None,
    check_in: date | None = None,
    nights: int | None = None,
    meal_plan: str | None = None,
    price_max: int | None = None,
    stars_min: int | None = None,
    adults: int | None = None,
    kids: list[int] | None = None,
    sort: str = "price_asc",
    limit: int = 20,
    offset: int = 0,
) -> PaginatedSearchResults:
    """Hotel facet search with real prices from `current_prices`."""
    order_by = _SORT_ORDER_BY.get(sort, _SORT_ORDER_BY["price_asc"])

    # Meal plan: expand canonical key ('all_inclusive') → raw codes
    # ['AI', 'UAI']. Raw codes pass through as singletons (back-compat).
    # When omitted, the SQL skips the meal filter entirely.
    meal_codes = raw_codes_for(meal_plan) if meal_plan else None
    current_price_meal_filter = "AND cp.meal_plan IN :meal_codes" if meal_codes else ""
    current_price_date_filter = (
        "AND cp.check_in = CAST(:check_in AS DATE)" if check_in is not None else ""
    )
    exact_first_order = (
        "CASE WHEN cp.nights = CAST(:nights AS INTEGER) THEN 0 ELSE 1 END,"
        if nights is not None
        else ""
    )
    requested_nights_expr = "CAST(:nights AS INTEGER)" if nights is not None else "NULL::INTEGER"

    params: dict[str, object] = {
        "country": country.upper() if country else None,
        "check_in": check_in,
        "nights": nights,
        "price_max": price_max,
        "stars_min": stars_min,
        "limit": limit,
        "offset": offset,
    }
    if meal_codes:
        params["meal_codes"] = meal_codes

    prices_cte = f"""
        prices AS (
            SELECT
                cp.hotel_id,
                (ARRAY_AGG(
                    cp.price_uah
                    ORDER BY {exact_first_order} cp.price_uah ASC NULLS LAST, cp.observed_at DESC
                ))[1] AS effective_price,
                (ARRAY_AGG(
                    cp.nights
                    ORDER BY {exact_first_order} cp.price_uah ASC NULLS LAST, cp.observed_at DESC
                ))[1] AS effective_nights,
                (ARRAY_AGG(
                    cp.deep_link
                    ORDER BY {exact_first_order} (cp.deep_link IS NULL), cp.price_uah ASC NULLS LAST, cp.observed_at DESC
                ))[1] AS deep_link,
                {requested_nights_expr} AS requested_nights,
                COALESCE(BOOL_OR(cp.nights = CAST(:nights AS INTEGER)), FALSE) AS nights_exact,
                MAX(cp.observed_at) AS last_observed_at
            FROM current_prices cp
            WHERE 1=1
              {current_price_date_filter}
              {current_price_meal_filter}
            GROUP BY cp.hotel_id
        )
    """
    join_clause = "JOIN prices px ON px.hotel_id = h.id"

    # Common WHERE fragments. We use CAST(:x AS TYPE) IS NULL so asyncpg
    # can infer parameter types when the filter is absent (same pattern
    # used in calendar_service.get_offers).
    #
    # `has_active_prices` filter: only surface hotels that have at least one
    # recent (≤14d) price observation. After the synthetic-data purge we
    # have ~652 fv-* hotels in the catalog but only ~148 have prices today;
    # showing the empty ones in search results creates a "ghost catalog"
    # experience (cards with no min_price_uah, dead-ends on click). The
    # catalog snapshot job keeps `last_seen_at` fresh; the price snapshot
    # job flips `has_active_prices` true/false. Search trusts that flag.
    base_where = """
        h.is_active = true
        AND h.has_active_prices = true
        AND (CAST(:country AS CHAR(2)) IS NULL
             OR d.country_iso2 = CAST(:country AS CHAR(2)))
        AND (CAST(:stars_min AS INTEGER) IS NULL
             OR h.stars >= CAST(:stars_min AS INTEGER))
        AND (CAST(:price_max AS INTEGER) IS NULL
             OR px.effective_price <= CAST(:price_max AS INTEGER))
    """

    # Count + page in two queries. We deliberately don't wrap them in a
    # CTE-with-window-count: pg can't share the CTE plan across two
    # statements anyway, and the COUNT is cheap (no ORDER BY, no LIMIT).
    count_sql = text(
        f"""
        WITH {prices_cte}
        SELECT COUNT(*) AS total
        FROM hotels h
        LEFT JOIN destinations d ON d.id = h.destination_id
        {join_clause}
        WHERE {base_where}
        """
    )
    if meal_codes:
        count_sql = count_sql.bindparams(bindparam("meal_codes", expanding=True))

    # Page query. Project the columns SearchResultItem needs. h.id at the
    # end of every whitelisted sort makes pagination stable when values tie.
    page_sql = text(
        f"""
        WITH {prices_cte}
        SELECT
            h.id              AS hotel_id,
            h.canonical_slug  AS canonical_slug,
            h.name_uk         AS name_uk,
            h.stars           AS stars,
            h.destination_id  AS destination_id,
            d.name_uk         AS destination_name,
            px.effective_price AS min_price_uah,
            px.deep_link      AS deep_link,
            px.requested_nights AS requested_nights,
            px.effective_nights AS effective_nights,
            px.last_observed_at AS last_observed_at,
            h.review_score    AS review_score,
            h.review_count    AS review_count,
            -- Search-result cards need a thumbnail; without one the grid
            -- looks broken. We pull the whole jsonb (small — usually
            -- 1 object × ~150 bytes) so the frontend can pick whichever
            -- index it wants. Empty array = no photo, render placeholder.
            COALESCE(h.photos_jsonb, '[]'::jsonb) AS photos
        FROM hotels h
        LEFT JOIN destinations d ON d.id = h.destination_id
        {join_clause}
        WHERE {base_where}
        ORDER BY
{order_by}
        LIMIT :limit OFFSET :offset
        """
    )
    if meal_codes:
        page_sql = page_sql.bindparams(bindparam("meal_codes", expanding=True))

    total = await session.scalar(count_sql, params) or 0
    rows = (await session.execute(page_sql, params)).mappings().all()

    items = [
        SearchResultItem(
            hotel_id=row["hotel_id"],
            canonical_slug=row["canonical_slug"],
            name_uk=row["name_uk"],
            stars=row["stars"],
            destination_id=row["destination_id"],
            destination_name=row.get("destination_name"),
            min_price_uah=(int(row["min_price_uah"]) if row["min_price_uah"] is not None else None),
            deep_link=row["deep_link"],
            requested_nights=(
                int(row["requested_nights"]) if row["requested_nights"] is not None else None
            ),
            effective_nights=(
                int(row["effective_nights"]) if row["effective_nights"] is not None else None
            ),
            review_score=(float(row["review_score"]) if row["review_score"] is not None else None),
            review_count=int(row.get("review_count") or 0),
            last_observed_at=row["last_observed_at"],
            nights_fallback=(
                row["requested_nights"] is not None
                and row["effective_nights"] is not None
                and int(row["requested_nights"]) != int(row["effective_nights"])
            ),
            # asyncpg already decoded the jsonb → Python list; defensive
            # coalesce in case a future driver returns None instead.
            photos=list(row["photos"] or []),
        )
        for row in rows
    ]

    requested_adults = adults or 2
    requested_kids = kids or []
    pax_supported = requested_adults == 2 and requested_kids == []
    pax_note = None
    if not pax_supported:
        pax_note = (
            "MVP price snapshots are currently collected for 2 adults without children; "
            "the hotel/price ranking below uses that basis."
        )

    return PaginatedSearchResults(
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
        price_basis_adults=2,
        price_basis_kids=[],
        pax_supported=pax_supported,
        pax_note=pax_note,
    )
