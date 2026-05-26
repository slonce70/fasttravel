"""indexes for search hot-paths

Revision ID: 005
Revises: 004
Create Date: 2026-05-23

Why: the DB audit flagged two queries doing Seq Scan that will become
hot-paths in prod:

1. `apps/api/src/services/search_service.py:96-124` —
   `WHERE check_in = ? AND meal_plan IN (...)` against
   `hotel_calendar_prices`. The existing `uq_hotel_calendar_prices_key`
   leads with `hotel_id` so the planner Seq-Scans (currently 11ms on
   32k rows; at 1M projected → 300ms+).

2. `apps/scheduler/src/jobs/detect_deals.py:104-110` cold-start CTE —
   `WHERE check_in BETWEEN ... AND ...` against `current_prices`. Today
   Parallel Seq Scan 216k rows (67ms); projected 2M+ → 600ms+ per tick.

3. Migration 004's `idx_deals_unposted_real` is a strict subset of the
   pre-existing `ix_deals_unposted` from 001. Drop the broader one;
   post_deals filters on the narrower (source IS NOT NULL) which 004
   already covers.

Two new indexes + one drop. All operations done on MVs and the deals
table (small) so we don't need CONCURRENTLY (the alembic transaction is
fine for this size). When tables grow to 100M rows revisit with
`CONCURRENTLY` + `--sql` output applied out-of-band.
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Search by (check_in, meal_plan) on the calendar MV. INCLUDE
    # carries the price columns the search aggregate needs so the index
    # is fully covering.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hcp_checkin_meal
        ON hotel_calendar_prices (check_in, meal_plan)
        INCLUDE (hotel_id, min_price_uah, min_7n, min_10n, min_14n)
        """
    )
    # 2. detect_deals cold-start window scan. Single-column (check_in)
    # with INCLUDE for the columns we project, so the index entry is
    # a fully-covering tuple — index-only scan when stats are fresh.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cur_prices_checkin
        ON current_prices (check_in)
        INCLUDE (hotel_id, operator_id, price_uah, nights, meal_plan, deep_link)
        """
    )
    # 3. Drop the now-superset deals index. The 004 partial index
    # (posted_at IS NULL AND source IS NOT NULL) is the only one
    # post_deals actually selects.
    op.execute("DROP INDEX IF EXISTS ix_deals_unposted")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cur_prices_checkin")
    op.execute("DROP INDEX IF EXISTS idx_hcp_checkin_meal")
    # Restore the dropped index so a rollback to 004 has the same shape
    # as the 001-init definition.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_deals_unposted
        ON deals (detected_at)
        WHERE posted_at IS NULL
        """
    )
