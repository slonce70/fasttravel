"""deals: prevent duplicate detections inside cooldown window

Revision ID: 006
Revises: 005
Create Date: 2026-05-23

Why: the Reality Checker audit flagged 5 `deals` rows with the same
`(hotel_id, check_in, nights, meal_plan)` tuple. Cause: `detect_deals`
only guards against repeats with a subquery cooldown check; two
parallel ticks (currently rare but possible during catch-up after a
scheduler restart) can both pass that check at the same instant and
both INSERT.

A real UNIQUE constraint across the natural key plus
`ON CONFLICT DO NOTHING` in the writer would be the bullet-proof fix,
but two facts complicate that:

  * The cooldown is intentionally 24h — a deal CAN legitimately
    reappear after the cooldown expires. A naive UNIQUE on the
    natural key blocks valid re-insertions.
  * `detect_deals` uses a single INSERT … SELECT statement; switching
    to `INSERT … ON CONFLICT` requires referencing a constraint name.

Solution: a partial UNIQUE INDEX that only counts deals detected
inside the cooldown window. Hand-roll the time-bound predicate with
`detected_at >= NOW() - INTERVAL '24 hours'`. The predicate is
`STABLE`, not `IMMUTABLE`, so Postgres rejects it in a normal partial
index — workaround: use a expression index keyed on a *bucketed*
timestamp truncated to the day.

Simpler approach: a regular UNIQUE index on
`(hotel_id, check_in, nights, meal_plan, (detected_at AT TIME ZONE 'UTC')::date)`.
Same hotel × same offer × same day → one row. Tomorrow's detection
gets its own row (date_trunc moves) → cooldown is enforced by the
SQL subquery as before, but a same-tick race now hits the
constraint and silently drops the loser.

Backfill: clean existing dupes before adding the constraint, keeping
the row with the highest `discount_pct` per group.
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. De-duplicate existing rows. Keep the most-discounted row per
    # natural-key + day bucket; tie-break by lowest id (stable).
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY hotel_id, check_in, nights, meal_plan,
                                 (detected_at AT TIME ZONE 'UTC')::date
                    ORDER BY discount_pct DESC, id ASC
                ) AS rn
            FROM deals
        )
        DELETE FROM deals
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # 2. The constraint itself. Names follow the project's snake_case
    # convention. Includes date_trunc bucket so re-detections on
    # subsequent days are still allowed.
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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_deals_natural_key_day")
    # NB: cannot un-de-duplicate the rows we deleted — downgrade is
    # constraint-only.
