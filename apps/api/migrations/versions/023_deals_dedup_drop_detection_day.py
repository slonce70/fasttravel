"""deals dedup: drop the per-day component from the natural key

Revision ID: 023
Revises: 022
Create Date: 2026-06-02

The migration-014 unique index ``uq_deals_natural_key_day`` includes
``((detected_at AT TIME ZONE 'UTC')::date)``, so a persistent deal
re-detected on consecutive days inserts a NEW row each day (``ON CONFLICT
DO NOTHING`` only dedups within a calendar day). On live data this had
accumulated ~1271 duplicate rows for the same logical deal.

This migration collapses each ``(hotel_id, check_in, nights, meal_plan,
detection_method)`` group to a single canonical row and replaces the index
with a date-free one, so the same deal can only ever exist once (the 24h
per-hotel cooldown still governs re-detection; a given check-in date is a
one-time event so re-posting it daily was pure spam).

Subscriber safety: ``telegram_filter_notifications.deal_id`` is
``ON DELETE CASCADE``, so before deleting duplicates we re-point any
notification-ledger rows onto the surviving canonical deal (``ON CONFLICT
DO NOTHING`` against the ``(filter_id, deal_id)`` PK). This preserves
notification history so subscribers are not re-notified for a deal they
already received. The canonical row is chosen as: a posted row
(``telegram_msg_id IS NOT NULL``) first, then the earliest ``detected_at``,
then the lowest ``id``.

Downgrade restores the per-day index; the deleted duplicate rows are not
recoverable (data cleanup is one-way), which is acceptable — they were
redundant re-detections.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


_RANKED = """
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY hotel_id, check_in, nights, meal_plan, detection_method
            ORDER BY (telegram_msg_id IS NOT NULL) DESC, detected_at ASC, id ASC
        ) AS rn,
        FIRST_VALUE(id) OVER (
            PARTITION BY hotel_id, check_in, nights, meal_plan, detection_method
            ORDER BY (telegram_msg_id IS NOT NULL) DESC, detected_at ASC, id ASC
        ) AS keep_id
    FROM deals
"""


def upgrade() -> None:
    # 1. Re-point notification-ledger rows from soon-to-be-deleted duplicate
    #    deals onto the surviving canonical row, so the CASCADE in step 2 does
    #    not erase notification history (which would let a subscriber be
    #    re-notified for a deal they already received).
    op.execute(
        f"""
        WITH ranked AS ({_RANKED})
        INSERT INTO telegram_filter_notifications (filter_id, deal_id, sent_at)
        SELECT t.filter_id, r.keep_id, t.sent_at
        FROM telegram_filter_notifications t
        JOIN ranked r ON r.id = t.deal_id
        WHERE r.rn > 1 AND r.keep_id <> t.deal_id
        ON CONFLICT (filter_id, deal_id) DO NOTHING
        """
    )
    # 2. Delete duplicate deal rows (CASCADE drops their now-redundant ledger rows).
    op.execute(
        f"""
        WITH ranked AS ({_RANKED})
        DELETE FROM deals WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    # 3. Replace the natural-key index without the per-day component.
    op.execute("DROP INDEX IF EXISTS uq_deals_natural_key_day")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_deals_natural_key
        ON deals (hotel_id, check_in, nights, meal_plan, detection_method)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_deals_natural_key")
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
