"""Per-filter notification ledger for subscriber deal alerts

Revision ID: 019
Revises: 018
Create Date: 2026-05-28

`telegram_subscriber_filters.last_notified_deal_id` is a scalar cursor,
but `notify_subscribers` intentionally picks the deepest discount first.
Those two ideas conflict: after sending deal id 12, matching deals 10 and
11 sit below the cursor and can never be alerted.

This ledger makes idempotency explicit per (filter, deal), so the job can
keep choosing the best current match without losing other valid matches.
The legacy cursor remains as an operational high-water mark.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _meal_plan_match_sql() -> str:
    """Frozen copy of the meal-plan filter semantics at revision 019."""
    return """
          (
            f.meal_plan IS NULL
            OR d.meal_plan = f.meal_plan
            OR (f.meal_plan = 'all_inclusive' AND d.meal_plan IN ('AI', 'UAI'))
            OR (f.meal_plan = 'half_board' AND d.meal_plan IN ('HB'))
            OR (f.meal_plan = 'breakfast' AND d.meal_plan IN ('BB'))
            OR (f.meal_plan = 'room_only' AND d.meal_plan IN ('RO'))
            OR (f.meal_plan = 'full_board' AND d.meal_plan IN ('FB'))
          )
    """.strip()


def upgrade() -> None:
    op.create_table(
        "telegram_filter_notifications",
        sa.Column(
            "filter_id",
            sa.BigInteger,
            sa.ForeignKey("telegram_subscriber_filters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "deal_id",
            sa.Integer,
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tfn_deal_id",
        "telegram_filter_notifications",
        ["deal_id"],
    )
    op.execute(
        "CREATE INDEX ix_tfn_filter_sent_at "
        "ON telegram_filter_notifications (filter_id, sent_at DESC)"
    )

    # Avoid a one-time resend storm on deploy. Historical rows below the
    # legacy cursor may or may not have been sent, but treating them as
    # already handled preserves the previous no-duplicate contract while
    # fixing the cursor behavior for newly detected deals.
    op.execute(
        f"""
        INSERT INTO telegram_filter_notifications (filter_id, deal_id, sent_at)
        SELECT f.id, d.id, NOW()
        FROM telegram_subscriber_filters f
        JOIN deals d
          ON f.last_notified_deal_id IS NOT NULL
         AND d.id <= f.last_notified_deal_id
         AND d.detected_at >= NOW() - INTERVAL '24 hours'
        JOIN hotels h ON h.id = d.hotel_id
        LEFT JOIN destinations dest ON dest.id = h.destination_id
        WHERE f.is_active
          AND dest.country_iso2 = f.country_iso2
          AND (f.max_price_uah IS NULL OR d.price_uah <= f.max_price_uah)
          AND (f.min_stars IS NULL OR h.stars >= f.min_stars)
          AND {_meal_plan_match_sql()}
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tfn_filter_sent_at", table_name="telegram_filter_notifications")
    op.drop_index("ix_tfn_deal_id", table_name="telegram_filter_notifications")
    op.drop_table("telegram_filter_notifications")
