"""hotels: scrape-freshness columns + idx for catalog-vs-price split

Revision ID: 003
Revises: 002
Create Date: 2026-05-23

Why: P1-1/P1-2 split the farvater pipeline into two independent jobs:

* `snapshot_catalog_farvater` (daily 03:00) — touches HTML hotel pages
  only, refreshes name/photo/stars/description, bumps `last_seen_at`.
  Cheap; can run on the whole catalog.

* `snapshot_farvater` (2× day) — calls the price-calendar endpoint,
  writes `price_observations`, bumps `last_priced_at` and flips
  `has_active_prices` to TRUE when at least one row was written.

Search reads `has_active_prices = TRUE` to keep the result set
honest: a hotel that's still in the catalog but where farvater no
longer surfaces availability shouldn't drown out the ones with
actual prices.

Columns:
  hotels.last_seen_at        timestamptz NULL   — catalog crawl heartbeat
  hotels.last_priced_at      timestamptz NULL   — price crawl heartbeat
  hotels.has_active_prices   boolean default false NOT NULL — search gate

Partial index on (has_active_prices) speeds up the most common
search WHERE — filtering live hotels — without paying for the dead
ones.

Backfill at migration time: any hotel that already has a row in
price_observations within the last 7 days is marked has_active_prices
and gets last_priced_at = the most-recent observed_at. last_seen_at
gets bootstrapped to last_priced_at OR last_updated OR NOW() so search
doesn't grade everything as "stale".
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hotels",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hotels",
        sa.Column("last_priced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hotels",
        sa.Column(
            "has_active_prices",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    # Backfill from recent observations so the search gate doesn't hide
    # everything on first deploy.
    op.execute(
        """
        UPDATE hotels h
        SET
            last_priced_at = sub.last_obs,
            last_seen_at   = COALESCE(sub.last_obs, h.last_updated, NOW()),
            has_active_prices = sub.last_obs IS NOT NULL
                                 AND sub.last_obs >= NOW() - INTERVAL '7 days'
        FROM (
            SELECT hotel_id, MAX(observed_at) AS last_obs
            FROM price_observations
            GROUP BY hotel_id
        ) sub
        WHERE sub.hotel_id = h.id
        """
    )
    # Synthetic seeds without any observations: bootstrap last_seen_at
    # so they show up in catalog UI but stay out of price-gated search.
    op.execute(
        """
        UPDATE hotels
        SET last_seen_at = COALESCE(last_seen_at, last_updated, NOW())
        WHERE last_seen_at IS NULL
        """
    )

    # Partial index — only the rows search actually filters on.
    op.create_index(
        "idx_hotels_active_priced",
        "hotels",
        ["destination_id"],
        unique=False,
        postgresql_where=sa.text("has_active_prices = TRUE AND is_active = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("idx_hotels_active_priced", table_name="hotels")
    op.drop_column("hotels", "has_active_prices")
    op.drop_column("hotels", "last_priced_at")
    op.drop_column("hotels", "last_seen_at")
