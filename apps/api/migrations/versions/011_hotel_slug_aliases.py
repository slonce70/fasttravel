"""hotel slug aliases for canonical redirects

Revision ID: 011
Revises: 010
Create Date: 2026-05-24

Farvater can expose multiple URL slugs for the same stable hotelKey. Keep
historical slugs as aliases to the canonical hotel instead of creating new
hotel rows and stale calendars.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

DUPLICATE_SLUG = "fv-es-apart-hotel-ght-tossa-park"
CANONICAL_SLUG = "fv-es-tossa-park-aparthotel"


def upgrade() -> None:
    op.create_table(
        "hotel_slug_aliases",
        sa.Column("source_slug", sa.String(160), primary_key=True),
        sa.Column(
            "hotel_id",
            sa.Integer,
            sa.ForeignKey("hotels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_hotel_slug_aliases_hotel_id", "hotel_slug_aliases", ["hotel_id"])

    op.execute(
        sa.text(
            """
            WITH canonical AS (
                SELECT id
                FROM hotels
                WHERE canonical_slug = :canonical_slug
                LIMIT 1
            ),
            duplicate AS (
                SELECT canonical_slug
                FROM hotels
                WHERE canonical_slug = :duplicate_slug
                LIMIT 1
            )
            INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
            SELECT duplicate.canonical_slug, canonical.id, 'farvater_duplicate_slug'
            FROM canonical, duplicate
            ON CONFLICT (source_slug) DO UPDATE
            SET hotel_id = EXCLUDED.hotel_id,
                reason = EXCLUDED.reason
            """
        ).bindparams(canonical_slug=CANONICAL_SLUG, duplicate_slug=DUPLICATE_SLUG)
    )
    op.execute(
        sa.text(
            """
            WITH canonical AS (
                SELECT id
                FROM hotels
                WHERE canonical_slug = :canonical_slug
                LIMIT 1
            )
            DELETE FROM hotels h
            USING canonical
            WHERE h.canonical_slug = :duplicate_slug
              AND h.id <> canonical.id
            """
        ).bindparams(canonical_slug=CANONICAL_SLUG, duplicate_slug=DUPLICATE_SLUG)
    )

    for mv in ("current_prices", "hotel_calendar_prices", "price_baselines"):
        op.execute(sa.text(f"REFRESH MATERIALIZED VIEW {mv}"))


def downgrade() -> None:
    op.drop_index("ix_hotel_slug_aliases_hotel_id", table_name="hotel_slug_aliases")
    op.drop_table("hotel_slug_aliases")
