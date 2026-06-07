"""Shared SQL for the "Найдешевші тури" (cheapest tours) surface.

This is the **absolute-cheap** companion to the anomaly date-dip detector — it
surfaces genuinely cheap upcoming tours (lowest price per tour), NOT relative
discounts. There is no «−X%», no strike-through, no baseline: the only honest
claim it makes is «ціна від» (price from). It deliberately shows the near-term /
low-season cheap dates that :mod:`apps.shared.deal_detection` intentionally
ignores, so they still get visibility.

Approach (no new table): one query builder over the ``current_prices`` MV joined
to ``hotels`` / ``destinations``. The API endpoint and any scheduler digest read
this single source so "cheapest" means the same thing on every surface.

Selection, in stages so the filters land in the right place:

  1. **base scan** of ``current_prices`` with all three gates applied up front —
     ``h.stars >= :min_stars`` (NULL stars fall out: NULL >= 3 is false),
     ``check_in`` in **+3..+90 days**, and the **freshness gate**
     ``observed_at >= NOW() - INTERVAL '<max_candidate_age_hours> hours'``
     (same constant as ``DATE_DIP_POLICY.max_candidate_age_hours`` so a price we
     show was re-confirmed recently). Freshness is filtered BEFORE the per-hotel
     minimum so a hotel whose cheapest offer is stale surfaces its next-cheapest
     *fresh* offer instead of vanishing.
  2. **per hotel** cheapest offer via ``DISTINCT ON (hotel_id)`` ordered by
     ``price_uah ASC`` with a deterministic tail, carrying
     operator_id / nights / meal_plan / check_in / room_category / deep_link.
  3. **per country** ``ROW_NUMBER() OVER (PARTITION BY country_iso2 ORDER BY
     price_uah ASC, hotel_id)`` → keep ``rank <= :per_country`` (default 3), so
     the output is TOP-N **distinct hotels** per country, diverse across resorts.

``country_name`` is resolved from the country-root destination (the single
``parent_id IS NULL`` row per ``country_iso2``); a hotel sitting directly on the
root resolves to itself, so this works on today's flat data and any future
region hierarchy alike.

Bind parameters: ``:min_stars`` and ``:per_country``. The freshness window and
the lookahead bounds are baked from module constants (trusted literals, never
user input), mirroring the style of :mod:`apps.shared.deal_detection`.
"""

from __future__ import annotations

from shared.deal_detection import DATE_DIP_POLICY

# Owner knobs (see docs/superpowers/specs/2026-06-03-cheapest-tours-design.md).
# PER_COUNTRY / MIN_STARS are this surface's own defaults; the freshness window
# is REUSED from the detector policy so a "cheapest" price is held to exactly
# the same re-confirmation bar as a published dip.
PER_COUNTRY = 3
MIN_STARS = 3
FRESHNESS_HOURS = DATE_DIP_POLICY.max_candidate_age_hours

# All-inclusive meal codes (raw Farvater codes). The channel digest filters to
# these so it shows «все включено» tours.
ALL_INCLUSIVE_MEAL_CODES = ("AI", "UAI")

# Channel-digest knobs: Turkey & Egypt (the all-inclusive hotspots) get more
# variants in the daily digest; every other country keeps the default.
DIGEST_PER_COUNTRY = 3
DIGEST_PRIORITY_COUNTRIES = ("TR", "EG")
DIGEST_PRIORITY_PER_COUNTRY = 5

# Lookahead window: skip the next 3 days (too close to book / depart) and cap at
# +90 days (the MV only retains check_in up to CURRENT_DATE + 90d anyway).
LOOKAHEAD_START_DAYS = 3
LOOKAHEAD_END_DAYS = 90


def cheapest_tours_sql(*, meal_filtered: bool = False, prioritized: bool = False) -> str:
    """Render the cheapest-tours selection SQL.

    Bind parameters: ``:min_stars`` (int), ``:per_country`` (int). With
    ``meal_filtered=True`` it also expects ``:meal_codes`` (list[str]) and only
    counts offers on those meal plans (the digest passes the all-inclusive
    codes). With ``prioritized=True`` it also expects ``:priority_countries``
    (list[str]) and ``:priority_per_country`` (int), giving those countries a
    larger per-country cap (the digest gives Turkey & Egypt more variants).
    Both default off, so the API/web/bot callers are unchanged.

    Returns a flat ranked list (one row per hotel); clients group by
    ``country_iso2``.

    Output columns: ``country_iso2, country_name, hotel_id, hotel_slug,
    hotel_name, stars, review_score, review_count, check_in, nights,
    meal_plan, price_uah, deep_link, rank``.
    """
    # Cast the array binds to text[] so asyncpg can infer the parameter type
    # (a bare `= ANY(:list)` fails to infer inside a CASE/WHERE).
    meal_clause = "AND cp.meal_plan = ANY(CAST(:meal_codes AS text[]))" if meal_filtered else ""
    rank_limit = (
        # CAST the int branches too: inside a CASE asyncpg can't infer the
        # param type and defaults to text, which breaks `bigint <= text`.
        "CASE WHEN r.country_iso2 = ANY(CAST(:priority_countries AS text[])) "
        "THEN CAST(:priority_per_country AS integer) "
        "ELSE CAST(:per_country AS integer) END"
        if prioritized
        else ":per_country"
    )
    return f"""
    WITH fresh_offers AS (
        -- Base scan: apply min-stars, the +{LOOKAHEAD_START_DAYS}..+{LOOKAHEAD_END_DAYS}d
        -- window and the freshness gate BEFORE collapsing per hotel, so a hotel
        -- whose cheapest offer is stale still surfaces its next-cheapest fresh one.
        SELECT
            h.id            AS hotel_id,
            h.canonical_slug AS hotel_slug,
            h.name_uk       AS hotel_name,
            h.stars         AS stars,
            h.review_score  AS review_score,
            h.review_count  AS review_count,
            d.country_iso2  AS country_iso2,
            cp.operator_id  AS operator_id,
            cp.check_in     AS check_in,
            cp.nights       AS nights,
            cp.meal_plan    AS meal_plan,
            cp.room_category AS room_category,
            cp.price_uah    AS price_uah,
            cp.deep_link    AS deep_link
        FROM current_prices cp
        JOIN hotels h ON h.id = cp.hotel_id
        JOIN destinations d ON d.id = h.destination_id
        WHERE h.is_active = true
          AND h.stars >= :min_stars
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '{LOOKAHEAD_START_DAYS} days'
                              AND CURRENT_DATE + INTERVAL '{LOOKAHEAD_END_DAYS} days'
          AND cp.observed_at >= NOW() - INTERVAL '{FRESHNESS_HOURS} hours'
          {meal_clause}
    ),
    per_hotel AS (
        -- Cheapest fresh offer per hotel. Deterministic tail
        -- (check_in, operator_id, nights, meal_plan, deep_link) so ties resolve
        -- the same way every run.
        SELECT DISTINCT ON (fo.hotel_id)
            fo.hotel_id, fo.hotel_slug, fo.hotel_name, fo.stars,
            fo.review_score, fo.review_count, fo.country_iso2,
            fo.operator_id, fo.check_in, fo.nights, fo.meal_plan,
            fo.room_category, fo.price_uah, fo.deep_link
        FROM fresh_offers fo
        ORDER BY fo.hotel_id,
                 fo.price_uah ASC,
                 fo.check_in ASC,
                 fo.operator_id ASC,
                 fo.nights ASC,
                 fo.meal_plan ASC,
                 fo.deep_link ASC
    ),
    ranked AS (
        -- TOP-:per_country distinct hotels per country, cheapest first.
        SELECT ph.*,
            ROW_NUMBER() OVER (
                PARTITION BY ph.country_iso2
                ORDER BY ph.price_uah ASC, ph.hotel_id ASC
            ) AS rank
        FROM per_hotel ph
    )
    SELECT
        r.country_iso2,
        -- Country name from the single parent_id IS NULL root per country;
        -- a hotel on the root itself resolves to its own name_uk.
        (SELECT root.name_uk
           FROM destinations root
          WHERE root.country_iso2 = r.country_iso2
            AND root.parent_id IS NULL
          ORDER BY root.id
          LIMIT 1) AS country_name,
        r.hotel_id,
        r.hotel_slug,
        r.hotel_name,
        r.stars,
        r.review_score,
        r.review_count,
        r.check_in,
        r.nights,
        r.meal_plan,
        r.price_uah,
        r.deep_link,
        r.rank
    FROM ranked r
    WHERE r.rank <= {rank_limit}
    ORDER BY country_name ASC, r.rank ASC, r.hotel_id ASC
    """
