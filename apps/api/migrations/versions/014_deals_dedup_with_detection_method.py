"""deals dedup constraint: include detection_method in natural key

Revision ID: 014
Revises: 013
Create Date: 2026-05-25

Sprint 1D made `detection_method` a first-class dimension on deals:
the same hotel can legitimately produce multiple same-day deals for
the same (check_in, nights, meal_plan) if they come from distinct
method families (for example historical `promo_discount` plus a
same-hotel anomaly).

The migration-006 unique index `uq_deals_natural_key_day` doesn't
account for that — it collapses different-method same-day rows into
one.

Fix: drop the old index, recreate it with `detection_method` in the
key tuple. Same-day re-detection in the same method is still blocked
(per-method cooldown enforced by SQL subquery); cross-method
co-detection is now legal.

Backfill is a no-op — the existing rows all have
`detection_method='percentile'` (server_default set in migration 013)
so they're already on a unique tuple with the new key.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_deals_natural_key_day")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_deals_natural_key_day
        ON deals (
            hotel_id,
            check_in,
            nights,
            meal_plan,
            detection_method,
            ((detected_at AT TIME ZONE 'UTC')::date)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_deals_natural_key_day")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_deals_natural_key_day
        ON deals (
            hotel_id,
            check_in,
            nights,
            meal_plan,
            ((detected_at AT TIME ZONE 'UTC')::date)
        )
        """
    )
