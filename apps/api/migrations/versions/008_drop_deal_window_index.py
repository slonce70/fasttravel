"""price_observations: drop suboptimal ix_price_obs_deal_window

Revision ID: 008
Revises: 007
Create Date: 2026-05-24

Audit DB Optimizer #7: `ix_price_obs_deal_window (observed_at, check_in)`
leads with `observed_at`, a near-monotonic timestamp with effectively zero
selectivity once the table grows past a day of data. Every deal-detection
query bottoms out in a scan that's wider than it needs to be, and Postgres
picks the calendar idx (`ix_price_obs_calendar`) anyway because it leads
with `hotel_id`.

We drop the bad one outright instead of replacing — calendar idx +
`uq_price_obs_natural` (migration 007) cover the predicates the deal
detector uses. If a future query genuinely needs `(check_in, observed_at)`
ordering we can re-add as a focused expression index.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_price_obs_deal_window")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_obs_deal_window "
        "ON price_observations (observed_at, check_in)"
    )
