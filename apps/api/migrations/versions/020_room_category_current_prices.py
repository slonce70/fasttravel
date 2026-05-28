"""Promote room_category into current price comparability

Revision ID: 020
Revises: 019
Create Date: 2026-05-28

Farvater returns multiple room categories for the same
hotel/operator/check-in/nights/meal tuple. We already persist
`room_category`, but `current_prices` used to collapse those rows because
its DISTINCT ON and unique index ignored the room. That made downstream
date-dip baselines wobble between incomparable rooms.

This migration keeps API contracts stable: search and calendar still
aggregate to the cheapest offer where appropriate, while offer/detail
queries can now see every current room row.
"""

from __future__ import annotations

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def _create_current_prices(include_room: bool) -> None:
    key = (
        "hotel_id, operator_id, check_in, nights, meal_plan, room_category"
        if include_room
        else "hotel_id, operator_id, check_in, nights, meal_plan"
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW current_prices AS
        SELECT DISTINCT ON ({key})
            hotel_id,
            operator_id,
            check_in,
            nights,
            meal_plan,
            room_category,
            price_uah,
            price_original,
            currency,
            deep_link,
            observed_at
        FROM price_observations
        WHERE check_in >= CURRENT_DATE
          AND check_in <= CURRENT_DATE + INTERVAL '90 days'
          AND observed_at >= NOW() - INTERVAL '14 days'
        ORDER BY {key}, observed_at DESC
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_current_prices_key
        ON current_prices ({key})
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
            MIN(min_price)                              AS min_price_uah,
            jsonb_object_agg(nights::text, min_price)   AS prices_by_night,
            MAX(last_observed_at)                       AS last_observed_at
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
    op.execute("ALTER TABLE price_observations ALTER COLUMN room_category SET DEFAULT ''")
    op.execute("UPDATE price_observations SET room_category = '' WHERE room_category IS NULL")
    op.execute("ALTER TABLE price_observations ALTER COLUMN room_category SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS uq_price_obs_natural")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_price_obs_natural
            ON price_observations (
                hotel_id, operator_id, check_in, nights,
                meal_plan, room_category, observed_at
            )
        """
    )
    _create_current_prices(include_room=True)
    _create_hotel_calendar_prices()


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE")
    op.execute("DROP INDEX IF EXISTS uq_price_obs_natural")
    op.execute("ALTER TABLE price_observations ALTER COLUMN room_category DROP NOT NULL")
    op.execute("ALTER TABLE price_observations ALTER COLUMN room_category DROP DEFAULT")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_price_obs_natural
            ON price_observations (
                hotel_id, operator_id, check_in, nights, meal_plan, observed_at
            )
        """
    )
    _create_current_prices(include_room=False)
    _create_hotel_calendar_prices()
