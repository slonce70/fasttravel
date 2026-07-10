"""heartbeats table for the systemd anti-reclamation keepalive

Revision ID: 024
Revises: 023
Create Date: 2026-06-12

infra/systemd/fasttravel-keepalive.timer inserts a row every hour to keep
the Oracle Always Free instance above the reclamation activity threshold.
The unit referenced this table since day one, but no migration ever created
it — every keepalive tick silently failed (masked by ON_ERROR_STOP=0), so
the anti-reclamation signal never existed.

The keepalive unit also deletes rows older than 7 days on each tick, so the
table stays at ~170 rows and needs no index.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "heartbeats",
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("heartbeats")
