"""deals: add source column for synthetic-vs-real filter

Revision ID: 004
Revises: 003
Create Date: 2026-05-23

Why: the Telegram broadcast must not announce demo seed deals as if
they were real. `price_observations.raw_payload->>'source'` already
records the ingest origin (`farvater_scrape`, `live_refresh`, or NULL
for synthetic seeds). We project that onto the `deals` row at
detection time so broadcast can filter cheaply with a WHERE.

Convention:
  source = 'farvater_scrape' | 'live_refresh' | 'ittour' | NULL
  NULL → synthetic seed → broadcast skips

The detect_deals query gets a small JOIN to read the source off the
matched current_prices row (which inherits raw_payload from the
most recent price_observations row via the MV's DISTINCT ON).

Backfill: any deal whose hotel canonical_slug starts with `fv-` is
flagged `farvater_scrape`; everything else stays NULL (synthetic).
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("source", sa.String(length=32), nullable=True),
    )
    # Backfill existing deals from hotel slug — close enough for
    # historical data; new inserts get source from the detector itself.
    op.execute(
        """
        UPDATE deals d
        SET source = 'farvater_scrape'
        FROM hotels h
        WHERE h.id = d.hotel_id
          AND h.canonical_slug LIKE 'fv-%'
          AND d.source IS NULL
        """
    )
    # Partial index for the broadcast's typical WHERE: posted_at IS NULL
    # AND source IS NOT NULL (only real deals get sent). Keeps the
    # planner happy on the inevitable 100k+-row deals table later.
    op.create_index(
        "idx_deals_unposted_real",
        "deals",
        ["detected_at"],
        unique=False,
        postgresql_where=sa.text("posted_at IS NULL AND source IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_deals_unposted_real", table_name="deals")
    op.drop_column("deals", "source")
