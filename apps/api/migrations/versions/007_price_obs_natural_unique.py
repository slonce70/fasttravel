"""price_observations: unique natural-key index

Revision ID: 007
Revises: 006
Create Date: 2026-05-24

Why: the audit DB Optimizer item #1 flagged that the table's PK is
`(id, observed_at)` only. Two concurrent writers can produce identical
`(hotel_id, operator_id, check_in, nights, meal_plan, observed_at)`
tuples — today rare (single scheduler instance) but blocks adding
parallel ingest sources (IT-Tour) cleanly.

The partition key (`observed_at`) must be part of any UNIQUE constraint
on a Postgres partitioned table, so it sits at the tail of the key.
Including microsecond-precise `observed_at` means same-tick batches
collide and harmlessly skip via `ON CONFLICT DO NOTHING`; different-
tick observations (12h snapshot, hourly refresh worker) coexist
because their `observed_at` differs.

`CONCURRENTLY` is NOT supported on partitioned tables in PG 16 — we
use plain CREATE INDEX. The table is small (currently ~14k rows) so
the lock is brief.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_price_obs_natural
            ON price_observations (
                hotel_id, operator_id, check_in, nights, meal_plan, observed_at
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_price_obs_natural")
