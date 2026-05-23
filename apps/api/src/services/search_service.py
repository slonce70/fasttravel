"""Hotel search service.

Reads `hotel_calendar_prices` MV (post migration 002, keyed on
hotel_id, check_in, meal_plan) so the search results carry a real
`min_price_uah` and can be sorted cheapest-first.

Two query regimes:

  1. `check_in` given → INNER JOIN the MV on `(hotel_id, check_in)`
     with an optional `meal_plan` filter. The effective price is
     `COALESCE(min_<nights>n, min_price_uah)` so a hotel without a
     7n/10n/14n bucket for that specific date still surfaces with its
     generic per-day MIN — better than NULL/dropped.

  2. `check_in` omitted → LEFT JOIN a subquery that gives the
     all-time MIN per hotel (optionally meal-plan-filtered). Hotels
     without any prices still appear (LEFT JOIN), sorted by
     review_score for editorial ranking.

ORDER BY is consistent across both regimes:
  effective_price ASC NULLS LAST, review_score DESC NULLS LAST.

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

# Whitelist for the nights → column mapping. Keeps a user-supplied int
# from sneaking into the SQL string. Anything outside this set falls back
# to the generic min_price_uah column.
_NIGHTS_COLUMN = {7: "min_7n", 10: "min_10n", 14: "min_14n"}


def _price_expr(nights: int | None, table_alias: str = "p") -> str:
    """Return the SQL expression for the per-hotel effective price.

    For 7/10/14 we COALESCE to min_price_uah so a hotel with offers for
    that day but not for the requested duration still surfaces with its
    generic minimum (the on-click offers fetch will narrow it down).
    """
    col = _NIGHTS_COLUMN.get(nights or 0)
    if col is None:
        return f"{table_alias}.min_price_uah"
    return f"COALESCE({table_alias}.{col}, {table_alias}.min_price_uah)"


async def search_hotels(
    session: AsyncSession,
    *,
    country: str | None = None,
    check_in: date | None = None,
    nights: int | None = None,
    meal_plan: str | None = None,
    price_max: int | None = None,
    stars_min: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> PaginatedSearchResults:
    """Hotel facet search with real prices from `hotel_calendar_prices`."""
    price_expr = _price_expr(nights)

    # Meal plan: expand canonical key ('all_inclusive') → raw codes
    # ['AI', 'UAI']. Raw codes pass through as singletons (back-compat).
    # When omitted, the SQL skips the meal filter entirely.
    meal_codes = raw_codes_for(meal_plan) if meal_plan else None
    meal_filter = "AND meal_plan IN :meal_codes" if meal_codes else ""

    params: dict[str, object] = {
        "country": country.upper() if country else None,
        "check_in": check_in,
        "price_max": price_max,
        "stars_min": stars_min,
        "limit": limit,
        "offset": offset,
    }
    if meal_codes:
        params["meal_codes"] = meal_codes

    # Build the price subquery / join differently depending on whether we
    # have a target date. The two CTEs always project the same columns:
    # (hotel_id, effective_price) — so the outer SELECT is identical.
    if check_in is not None:
        # Date-specific path: INNER JOIN the MV row(s) for that day. If a
        # hotel has no MV row for `check_in`, it does not appear in the
        # results — which matches user intent ("show me hotels with prices
        # for this date").
        prices_cte = f"""
            prices AS (
                SELECT
                    hotel_id,
                    MIN({price_expr}) AS effective_price
                FROM hotel_calendar_prices p
                WHERE check_in = CAST(:check_in AS DATE)
                  {meal_filter}
                GROUP BY hotel_id
            )
        """
        # INNER JOIN: a hotel only shows up if it has a row for that date.
        join_clause = "JOIN prices px ON px.hotel_id = h.id"
    else:
        # No-date path: pull the all-time MIN per hotel. LEFT JOIN so
        # hotels without ANY prices still appear; they sort to the
        # bottom thanks to ASC NULLS LAST. Frontend may want to show
        # them anyway (e.g. for browsing destinations).
        prices_cte = f"""
            prices AS (
                SELECT
                    hotel_id,
                    MIN({price_expr}) AS effective_price
                FROM hotel_calendar_prices p
                WHERE 1=1
                  {meal_filter}
                GROUP BY hotel_id
            )
        """
        join_clause = "LEFT JOIN prices px ON px.hotel_id = h.id"

    # Common WHERE fragments. We use CAST(:x AS TYPE) IS NULL so asyncpg
    # can infer parameter types when the filter is absent (same pattern
    # used in calendar_service.get_offers).
    base_where = """
        h.is_active = true
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

    # Page query. Project the columns SearchResultItem needs, ordering by
    # cheapest first (NULLS LAST so priceless hotels go to the bottom),
    # review_score as tiebreak. h.id at the end makes pagination stable
    # when prices and review_scores tie.
    page_sql = text(
        f"""
        WITH {prices_cte}
        SELECT
            h.id              AS hotel_id,
            h.canonical_slug  AS canonical_slug,
            h.name_uk         AS name_uk,
            h.stars           AS stars,
            h.destination_id  AS destination_id,
            px.effective_price AS min_price_uah,
            h.review_score    AS review_score
        FROM hotels h
        LEFT JOIN destinations d ON d.id = h.destination_id
        {join_clause}
        WHERE {base_where}
        ORDER BY
            px.effective_price ASC NULLS LAST,
            h.review_score     DESC NULLS LAST,
            h.id               ASC
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
            min_price_uah=(
                int(row["min_price_uah"]) if row["min_price_uah"] is not None else None
            ),
            review_score=(
                float(row["review_score"]) if row["review_score"] is not None else None
            ),
        )
        for row in rows
    ]

    return PaginatedSearchResults(
        items=items, total=int(total), limit=limit, offset=offset
    )
