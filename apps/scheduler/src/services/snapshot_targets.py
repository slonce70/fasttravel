"""Hotel target selection for the Farvater price snapshot."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PRICE_REFRESH_TARGETS_SQL = text(
    """
    -- Daily-price-refresh source. Picks active hotels in the selected
    -- countries, including previously priced hotels whose active price flag
    -- decayed. Iterating /hotelscatalog/strana-X/ would only cover
    -- farvater's curated top ~67 per country after the sitemap ingest landed.
    SELECT
        h.id,
        h.canonical_slug,
        d.country_iso2,
        COALESCE(hom.external_id, '') AS external_id,
        h.has_active_prices,
        h.last_priced_at
    FROM hotels h
    JOIN destinations d ON d.id = h.destination_id
    LEFT JOIN hotel_operator_mapping hom
           ON hom.hotel_id = h.id
          AND hom.operator_id =
              (SELECT id FROM operators WHERE code = 'farvater')
    WHERE h.is_active
      AND d.country_iso2 = ANY(:iso_filter)
      AND (
          h.has_active_prices = TRUE
          OR h.last_priced_at IS NULL
          OR h.last_priced_at < NOW() - make_interval(hours => CAST(:unpriced_cooldown_hours AS INTEGER))
      )
    ORDER BY
      h.has_active_prices DESC NULLS LAST,
      h.last_priced_at NULLS LAST,
      h.id
    """
)


def path_from_slug(slug: str) -> str | None:
    parts = slug.split("-", 2)
    if len(parts) != 3 or parts[0] != "fv":
        return None
    return f"/uk/hotel/{parts[1]}/{parts[2]}/"


async def refresh_targets(
    db: AsyncSession,
    iso_filter: list[str],
    max_per_country: int | None,
    *,
    unpriced_cooldown_hours: int = 24,
) -> list[tuple[str, str, int, str]]:
    """Return (url_path, iso2, hotel_db_id, external_id) tuples by refresh priority."""
    rows = (
        await db.execute(
            PRICE_REFRESH_TARGETS_SQL,
            {
                "iso_filter": iso_filter,
                "unpriced_cooldown_hours": unpriced_cooldown_hours,
            },
        )
    ).all()
    out: list[tuple[str, str, int, str]] = []
    per_country: dict[str, int] = {}
    for row in rows:
        iso2 = (row.country_iso2 or "").upper()
        if max_per_country is not None and per_country.get(iso2, 0) >= max_per_country:
            continue
        path = path_from_slug(row.canonical_slug)
        if not path:
            continue
        out.append((path, iso2, row.id, row.external_id or ""))
        per_country[iso2] = per_country.get(iso2, 0) + 1
    return out
