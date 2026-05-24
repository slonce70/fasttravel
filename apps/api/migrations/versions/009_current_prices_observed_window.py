"""current_prices MV: only include observations from the last 14 days

Revision ID: 009
Revises: 008
Create Date: 2026-05-24

Audit DB Optimizer #4: the MV pulls every price_observations row whose
`check_in` is in the next 90 days, with no upper bound on `observed_at`.
As retention grows (today 60 days, target 180 days) the MV scales
linearly with history — refresh time and storage both bloat for the same
"current price" answer.

We constrain to `observed_at >= NOW() - INTERVAL '14 days'`. 14 days is
generous: the daily snapshot runs every 12 hours and the user-triggered
refresh path keeps active hotels fresher than that. Anything older is
stale enough that a deal computed against it would mislead users.

The MV is rebuilt with the new WHERE clause and the unique index is
re-applied. We DROP + CREATE in one transaction so concurrent reads
either see the old or the new shape, never a partial state.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CASCADE drops dependent objects: current_prices indexes AND
    # hotel_calendar_prices MV (which selects from current_prices). We
    # rebuild all three plus the search indexes from migration 005 below.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE")
    op.execute(
        """
        CREATE MATERIALIZED VIEW current_prices AS
        SELECT DISTINCT ON (hotel_id, operator_id, check_in, nights, meal_plan)
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
          -- Window matches the refresh cadence (12h snapshot + on-demand
          -- refresh) with comfortable headroom; anything older is stale
          -- enough to mislead the deal detector.
          AND observed_at >= NOW() - INTERVAL '14 days'
        ORDER BY hotel_id, operator_id, check_in, nights, meal_plan, observed_at DESC
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_current_prices_key
        ON current_prices (hotel_id, operator_id, check_in, nights, meal_plan)
        """
    )
    # idx_cur_prices_checkin came from migration 005 — restore it so the
    # cold-start CTE in detect_deals stays fast.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cur_prices_checkin
        ON current_prices (check_in)
        INCLUDE (hotel_id, operator_id, nights, meal_plan, price_uah, deep_link)
        """
    )

    # Recreate hotel_calendar_prices (CASCADE'd above because it depended
    # on current_prices). Definition mirrors migration 002 (the version that
    # added meal_plan to the grouping key) so the API/UI surface stays unchanged.
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
    # Mirror migration 005's covering index — search-by-price uses it.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hcp_checkin_meal
        ON hotel_calendar_prices (check_in, meal_plan)
        INCLUDE (hotel_id, min_price_uah, min_7n, min_10n, min_14n)
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE")
    op.execute(
        """
        CREATE MATERIALIZED VIEW current_prices AS
        SELECT DISTINCT ON (hotel_id, operator_id, check_in, nights, meal_plan)
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
        ORDER BY hotel_id, operator_id, check_in, nights, meal_plan, observed_at DESC
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_current_prices_key
        ON current_prices (hotel_id, operator_id, check_in, nights, meal_plan)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cur_prices_checkin
        ON current_prices (check_in)
        INCLUDE (hotel_id, operator_id, nights, meal_plan, price_uah, deep_link)
        """
    )
