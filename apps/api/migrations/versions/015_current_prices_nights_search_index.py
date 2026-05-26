"""current_prices exact-nights search index

Revision ID: 015
Revises: 014
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_current_prices_nights_checkin_hotel
        ON current_prices (nights, check_in, hotel_id)
        INCLUDE (meal_plan, price_uah, deep_link, observed_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_current_prices_nights_checkin_hotel")
