"""seed known hotel slug aliases

Revision ID: 017
Revises: 016
Create Date: 2026-05-26

Some historical Farvater URLs point at the same stable hotel as the current
canonical slug. Keep these aliases independent from whether a duplicate hotel
row happened to exist when the aliases table was created.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

ALIASES = (
    (
        "fv-es-apart-hotel-ght-tossa-park",
        "fv-es-tossa-park-aparthotel",
        "farvater_legacy_duplicate_slug",
    ),
)


def upgrade() -> None:
    for source_slug, canonical_slug, reason in ALIASES:
        op.execute(
            sa.text(
                """
                INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
                SELECT :source_slug, h.id, :reason
                FROM hotels h
                WHERE h.canonical_slug = :canonical_slug
                ON CONFLICT (source_slug) DO UPDATE
                SET hotel_id = EXCLUDED.hotel_id,
                    reason = EXCLUDED.reason
                """
            ).bindparams(
                source_slug=source_slug,
                canonical_slug=canonical_slug,
                reason=reason,
            )
        )


def downgrade() -> None:
    for source_slug, _canonical_slug, _reason in ALIASES:
        op.execute(
            sa.text("DELETE FROM hotel_slug_aliases WHERE source_slug = :source_slug").bindparams(
                source_slug=source_slug
            )
        )
