"""hotel_calendar_prices: per-nights MIN as JSONB

Revision ID: 016
Revises: 015
Create Date: 2026-05-25

Stage 2 of the calendar-anomaly audit.

Background: snapshot_farvater now scrapes prices for all nights in
[7..14] — but `hotel_calendar_prices` only exposes `min_7n / min_10n /
min_14n` columns, so prices for nights 8/9/11/12/13 land in
`current_prices` and stop there. The hotel-page calendar UI then
fallback-displays `min_price_uah` for those nights, which is the
across-all-nights minimum and not what the user asked for.

Fix: replace the three hardcoded columns with a `prices_by_night JSONB`
map (`{"7": 50000, "8": 52000, ...}`). Schema becomes durable for any
future night-range expansion without further migrations, and the
frontend / API can render `?nights=N` for any N that has data.

`min_price_uah` and `last_observed_at` are kept — they're used by the
no-nights heatmap fallback and by the `current_prices` freshness checks
elsewhere in the API.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CASCADE drops dependent indexes — they get re-created below.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS hotel_calendar_prices CASCADE")
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        WITH per_night AS (
            -- Compute MIN per (hotel, day, meal, nights) so the JSONB
            -- aggregate downstream gets one entry per night with the
            -- cheapest offer for that duration.
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


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS hotel_calendar_prices CASCADE")
    # Restore the migration-009 shape so a rollback puts the API back to
    # exactly what it was before this migration.
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        SELECT
            hotel_id,
            check_in,
            meal_plan,
            MIN(price_uah)                            AS min_price_uah,
            MIN(price_uah) FILTER (WHERE nights = 7)  AS min_7n,
            MIN(price_uah) FILTER (WHERE nights = 10) AS min_10n,
            MIN(price_uah) FILTER (WHERE nights = 14) AS min_14n,
            MAX(observed_at)                          AS last_observed_at
        FROM current_prices
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
        INCLUDE (min_price_uah, min_7n, min_10n, min_14n)
        """
    )
