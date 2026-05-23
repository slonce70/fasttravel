"""GET /api/destinations — list of countries + regions for selectors / SEO.

This is a read-mostly facets endpoint. Two query shapes:

* `GET /api/destinations` → flat list of all countries, each with nested
  active regions and hotel counts. The frontend renders a country selector
  and generates static `/destinations/[country]` pages from this payload.
* `GET /api/destinations/{country_slug}` → one country with the same
  shape, used for the SEO destination landing page.

The implementation is a single SQL aggregating hotels by parent country
in one round-trip. Frontend caches with ISR (1h) so this endpoint is hit
infrequently — no need for a materialized view yet.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.destination import CountryOut, RegionOut

router = APIRouter(prefix="/api/destinations", tags=["destinations"])


# Map ISO2 → URL slug. Kept here (not in DB) because:
#   * slug is a frontend concern (SEO URLs) not a domain attribute,
#   * a country's slug stays stable once chosen; renaming a country in
#     destinations.name_en should never change its public URL.
ISO2_TO_SLUG: dict[str, str] = {
    "TR": "turkey",
    "EG": "egypt",
    "AE": "uae",
    "GR": "greece",
    "ES": "spain",
    "BG": "bulgaria",
    "ME": "montenegro",
    "HR": "croatia",
    "CY": "cyprus",
    "TH": "thailand",
    "MV": "maldives",
    "IT": "italy",
    "TN": "tunisia",
    "DO": "dominican-republic",
}

SLUG_TO_ISO2: dict[str, str] = {v: k for k, v in ISO2_TO_SLUG.items()}


_ALL_COUNTRIES_SQL = text(
    """
    -- We only count hotels with has_active_prices=true. The catalog
    -- (snapshot_catalog_farvater) adds every hotel farvater lists, but
    -- many sit there with no operator inventory — they show 0 results
    -- when a user actually searches. Counting them would inflate the
    -- destination headline and break the trust contract with
    -- /search results (which only surfaces priced hotels).
    WITH country AS (
        SELECT id, country_iso2, name_uk, name_en
        FROM destinations
        WHERE parent_id IS NULL
    ),
    region_counts AS (
        SELECT
            d.id,
            d.country_iso2,
            d.region_slug,
            d.name_uk,
            d.name_en,
            d.parent_id,
            COALESCE(
                COUNT(h.id) FILTER (WHERE h.is_active AND h.has_active_prices),
                0
            ) AS hotel_count
        FROM destinations d
        LEFT JOIN hotels h ON h.destination_id = d.id
        WHERE d.parent_id IS NOT NULL
        GROUP BY d.id
    ),
    -- Hotels can also be linked directly to the country-level destination
    -- (no region matched at ingest time). Same has_active_prices filter
    -- so the total stays consistent with what /search returns.
    country_direct_counts AS (
        SELECT d.id AS country_id,
               COALESCE(
                   COUNT(h.id) FILTER (WHERE h.is_active AND h.has_active_prices),
                   0
               ) AS direct_hotel_count
        FROM destinations d
        LEFT JOIN hotels h ON h.destination_id = d.id
        WHERE d.parent_id IS NULL
        GROUP BY d.id
    )
    SELECT
        c.id            AS country_id,
        c.country_iso2,
        c.name_uk       AS country_name_uk,
        c.name_en       AS country_name_en,
        (COALESCE(SUM(r.hotel_count), 0) + COALESCE(MAX(cdc.direct_hotel_count), 0))::int
            AS country_hotel_count,
        COALESCE(
            json_agg(
                json_build_object(
                    'id',           r.id,
                    'region_slug',  r.region_slug,
                    'name_uk',      r.name_uk,
                    'name_en',      r.name_en,
                    'hotel_count',  r.hotel_count
                )
                ORDER BY r.hotel_count DESC, r.name_uk
            ) FILTER (WHERE r.id IS NOT NULL AND r.hotel_count > 0),
            '[]'::json
        ) AS regions
    FROM country c
    LEFT JOIN region_counts r ON r.parent_id = c.id
    LEFT JOIN country_direct_counts cdc ON cdc.country_id = c.id
    GROUP BY c.id, c.country_iso2, c.name_uk, c.name_en
    ORDER BY country_hotel_count DESC, c.name_uk
    """
)


def _row_to_country(row) -> CountryOut:
    iso2 = row.country_iso2
    return CountryOut(
        id=row.country_id,
        country_iso2=iso2,
        country_slug=ISO2_TO_SLUG.get(iso2, iso2.lower()),
        name_uk=row.country_name_uk,
        name_en=row.country_name_en,
        hotel_count=int(row.country_hotel_count),
        regions=[RegionOut(**r) for r in row.regions],
    )


@router.get("", response_model=list[CountryOut])
async def list_destinations(
    session: AsyncSession = Depends(get_db),
) -> list[CountryOut]:
    """Return all countries with nested active regions + hotel counts."""
    result = await session.execute(_ALL_COUNTRIES_SQL)
    return [_row_to_country(row) for row in result]


@router.get("/{country_slug}", response_model=CountryOut)
async def get_destination(
    country_slug: str,
    session: AsyncSession = Depends(get_db),
) -> CountryOut:
    """Return one country by URL slug ('turkey', 'egypt', ...)."""
    iso2 = SLUG_TO_ISO2.get(country_slug.lower())
    if iso2 is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown country slug: {country_slug!r}",
        )

    # Filter in Python: with ~15 countries total, the in-process scan is
    # cheaper than a second specialised SQL query and keeps the aggregating
    # CTE single-source-of-truth.
    result = await session.execute(_ALL_COUNTRIES_SQL)
    for row in result:
        if row.country_iso2 == iso2:
            return _row_to_country(row)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Country {country_slug!r} has no destinations in catalog yet",
    )
