"""Materialize room_family for indexed date-dip comparisons

Revision ID: 021
Revises: 020
Create Date: 2026-05-28

`room_category` is still the source-of-truth room label, but Farvater
emits equivalent rooms with slightly different strings (`STUDIO SV`,
`Studio Sea View`, etc.). The detector needs to compare equivalent room
families without losing the date-dip lookup index.
"""

from __future__ import annotations

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

_STANDARD_ROOM_TOKENS = (
    "dbl",
    "double",
    "standard",
    "standart",
    "std",
    "classic",
    "room",
    "twin",
    "single",
    "sgl",
    "king",
    "queen",
    "roh",
    "run of house",
)

_ECONOMY_ROOM_TOKENS = (
    "budget",
    "economy",
    "econom",
    "eco",
    "promo",
    "best price",
)

_COMFORT_ROOM_TOKENS = ("comfort",)
_PREMIUM_ROOM_TOKENS = ("premium",)
_SUPERIOR_ROOM_TOKENS = ("superior",)
_DELUXE_ROOM_TOKENS = ("deluxe",)

_SEA_VIEW_TOKENS = (
    "sv",
    "ssv",
    "psv",
    "sea view",
    "sea side",
    "side sea",
    "sea front",
    "side sea view",
    "partial sea view",
    "sea side view",
    "seaside",
)

_LAND_VIEW_TOKENS = (
    "lv",
    "land view",
    "inland view",
)

_GARDEN_VIEW_TOKENS = (
    "gv",
    "garden",
    "garden view",
)

_POOL_VIEW_TOKENS = (
    "pv",
    "pool",
    "pool view",
)

_APARTMENT_ROOM_TOKENS = (
    "apartment",
    "apt",
    "app",
    "br",
    "bedroom",
)


def _room_token_condition(tokens: tuple[str, ...]) -> str:
    return "\n          OR ".join(
        f"(' ' || room_norm || ' ') LIKE '% {token} %'" for token in tokens
    )


_ROOM_FAMILY_SQL = f"""
(
    CASE
        WHEN (' ' || room_norm || ' ') LIKE '% studio %' THEN 'studio'
        WHEN (' ' || room_norm || ' ') LIKE '% suite %'
          OR (' ' || room_norm || ' ') LIKE '% junior suite %' THEN 'suite'
        WHEN (' ' || room_norm || ' ') LIKE '% bungalow %' THEN 'bungalow'
        WHEN (' ' || room_norm || ' ') LIKE '% villa %' THEN 'villa'
        WHEN {_room_token_condition(_APARTMENT_ROOM_TOKENS)} THEN 'apartment'
        WHEN (' ' || room_norm || ' ') LIKE '% family %' THEN 'family'
        WHEN {_room_token_condition(_DELUXE_ROOM_TOKENS)} THEN 'deluxe'
        WHEN {_room_token_condition(_SUPERIOR_ROOM_TOKENS)} THEN 'superior'
        WHEN {_room_token_condition(_PREMIUM_ROOM_TOKENS)} THEN 'premium'
        WHEN {_room_token_condition(_COMFORT_ROOM_TOKENS)} THEN 'comfort'
        WHEN {_room_token_condition(_ECONOMY_ROOM_TOKENS)} THEN 'economy'
        WHEN {_room_token_condition(_STANDARD_ROOM_TOKENS)} THEN 'standard'
        ELSE 'other'
    END
    || ':' ||
    CASE
        WHEN {_room_token_condition(_SEA_VIEW_TOKENS)} THEN 'sea'
        WHEN {_room_token_condition(_LAND_VIEW_TOKENS)} THEN 'land'
        WHEN {_room_token_condition(_GARDEN_VIEW_TOKENS)} THEN 'garden'
        WHEN {_room_token_condition(_POOL_VIEW_TOKENS)} THEN 'pool'
        ELSE 'any'
    END
)
"""


def _create_current_prices(include_family: bool) -> None:
    room_family_select = f"{_ROOM_FAMILY_SQL} AS room_family," if include_family else ""
    room_family_index = (
        """
        CREATE INDEX IF NOT EXISTS idx_current_prices_date_dip_family_lookup
        ON current_prices (hotel_id, operator_id, nights, meal_plan, room_family, check_in)
        INCLUDE (price_uah, deep_link, room_category)
        """
        if include_family
        else ""
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW current_prices AS
        SELECT
            hotel_id,
            operator_id,
            check_in,
            nights,
            meal_plan,
            room_category,
            {room_family_select}
            price_uah,
            price_original,
            currency,
            deep_link,
            observed_at
        FROM (
            SELECT DISTINCT ON (
                hotel_id, operator_id, check_in, nights, meal_plan, room_category
            )
                hotel_id,
                operator_id,
                check_in,
                nights,
                meal_plan,
                room_category,
                trim(regexp_replace(lower(coalesce(room_category, '')), '[^a-z0-9]+', ' ', 'g'))
                    AS room_norm,
                price_uah,
                price_original,
                currency,
                deep_link,
                observed_at
            FROM price_observations
            WHERE check_in >= CURRENT_DATE
              AND check_in <= CURRENT_DATE + INTERVAL '90 days'
              AND observed_at >= NOW() - INTERVAL '14 days'
            ORDER BY hotel_id, operator_id, check_in, nights, meal_plan, room_category,
                     observed_at DESC
        ) latest
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_current_prices_key
        ON current_prices (hotel_id, operator_id, check_in, nights, meal_plan, room_category)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cur_prices_checkin
        ON current_prices (check_in)
        INCLUDE (hotel_id, operator_id, nights, meal_plan, price_uah, deep_link)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_current_prices_nights_checkin_hotel
        ON current_prices (nights, check_in, hotel_id)
        INCLUDE (meal_plan, price_uah, deep_link, observed_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_current_prices_date_dip_lookup
        ON current_prices (hotel_id, operator_id, nights, meal_plan, room_category, check_in)
        INCLUDE (price_uah, deep_link)
        """
    )
    if room_family_index:
        op.execute(room_family_index)


def _create_hotel_calendar_prices() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        WITH per_night AS (
            SELECT
                hotel_id,
                check_in,
                meal_plan,
                nights,
                MIN(price_uah)   AS min_price,
                MAX(observed_at) AS last_observed_at
            FROM current_prices
            WHERE nights BETWEEN 7 AND 14
            GROUP BY hotel_id, check_in, meal_plan, nights
        )
        SELECT
            hotel_id,
            check_in,
            meal_plan,
            MIN(min_price)                            AS min_price_uah,
            jsonb_object_agg(nights::text, min_price) AS prices_by_night,
            MAX(last_observed_at)                     AS last_observed_at
        FROM per_night
        GROUP BY hotel_id, check_in, meal_plan
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_hotel_calendar_prices_key
        ON hotel_calendar_prices (hotel_id, check_in, meal_plan)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hcp_checkin_meal
        ON hotel_calendar_prices (check_in, meal_plan)
        INCLUDE (min_price_uah, prices_by_night)
        """
    )


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE")
    _create_current_prices(include_family=True)
    _create_hotel_calendar_prices()


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE")
    _create_current_prices(include_family=False)
    _create_hotel_calendar_prices()
