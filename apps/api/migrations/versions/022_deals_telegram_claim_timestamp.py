"""Add recoverable Telegram deal claim timestamp

Revision ID: 022
Revises: 021
Create Date: 2026-05-28

`post_deals` claims rows with a negative `telegram_msg_id` before sending to
Telegram. Without a claim timestamp, a scheduler crash between claim and
send/mark leaves that row invisible forever. The timestamp gives the claim a
bounded TTL while still preventing immediate duplicate sends.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("telegram_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE deals
        SET telegram_msg_id = NULL
        WHERE posted_at IS NULL
          AND telegram_msg_id = -1
          AND telegram_claimed_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_deals_pending_telegram_claim
        ON deals (telegram_claimed_at)
        WHERE posted_at IS NULL AND telegram_msg_id = -1
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_deals_pending_telegram_claim")
    op.drop_column("deals", "telegram_claimed_at")
