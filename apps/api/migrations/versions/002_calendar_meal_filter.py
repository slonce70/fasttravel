"""calendar: add meal_plan dimension to hotel_calendar_prices

Revision ID: 002
Revises: 001
Create Date: 2026-05-23

Why: the heatmap on the hotel page must change when the user toggles
AI/HB/BB — otherwise the headline price the user sees on the calendar
is the cheapest meal-plan price, even when they've explicitly asked for
"All-Inclusive only". Frontend was previously forced to ignore the
filter for the calendar view because the MV had no meal_plan column.

Schema change:
  hotel_calendar_prices is GROUPed BY (hotel_id, check_in)
                          -->  (hotel_id, check_in, meal_plan)
  uq_hotel_calendar_prices_key  --> (hotel_id, check_in, meal_plan)

Postgres can't ALTER a materialized view's column list; we have to
DROP + CREATE. The MV is created WITH NO DATA (matching ADR-011), so a
non-CONCURRENT priming refresh is required after the migration:

    REFRESH MATERIALIZED VIEW hotel_calendar_prices;

Hourly cron resumes CONCURRENTLY refreshes thereafter.

Backwards compatibility for callers that omit `meal_plan`:
  The API layer re-aggregates rows in `calendar_service.get_calendar`
  when no meal_plan is given (MIN across meal-plan rows for the same
  check_in). This keeps the public shape stable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DROP the old MV (and its index implicitly).
    op.execute("DROP MATERIALIZED VIEW IF EXISTS hotel_calendar_prices")

    # New MV: same columns plus meal_plan in the grouping key.
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        SELECT
            hotel_id,
            check_in,
            meal_plan,
            MIN(price_uah)                                            AS min_price_uah,
            MIN(price_uah) FILTER (WHERE nights = 7)                  AS min_7n,
            MIN(price_uah) FILTER (WHERE nights = 10)                 AS min_10n,
            MIN(price_uah) FILTER (WHERE nights = 14)                 AS min_14n,
            MAX(observed_at)                                          AS last_observed_at
        FROM current_prices
        GROUP BY hotel_id, check_in, meal_plan
        WITH NO DATA;
        """
    )
    # Unique index keeps the same name so downgrade/upgrade is stable;
    # the column set widens to include meal_plan.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_hotel_calendar_prices_key
        ON hotel_calendar_prices (hotel_id, check_in, meal_plan);
        """
    )


def downgrade() -> None:
    # Restore the exact MV definition from 001_init.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS hotel_calendar_prices")
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        SELECT
            hotel_id,
            check_in,
            MIN(price_uah)                                            AS min_price_uah,
            MIN(price_uah) FILTER (WHERE nights = 7)                  AS min_7n,
            MIN(price_uah) FILTER (WHERE nights = 10)                 AS min_10n,
            MIN(price_uah) FILTER (WHERE nights = 14)                 AS min_14n,
            MAX(observed_at)                                          AS last_observed_at
        FROM current_prices
        GROUP BY hotel_id, check_in
        WITH NO DATA;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_hotel_calendar_prices_key
        ON hotel_calendar_prices (hotel_id, check_in);
        """
    )
