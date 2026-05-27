"""Hotel.coords → PostGIS geography(Point, 4326)

Revision ID: 018
Revises: 017
Create Date: 2026-05-27

Audit #1.3 Low — `hotels.coords` was a plain `Text` column ("POINT(lng
lat)") with no spatial index. The first feature that needs "find hotels
near X" would have to ALTER the column anyway. Doing it now while the
table is still small is far cheaper than later.

Strategy:
  1. CREATE EXTENSION postgis IF NOT EXISTS.
  2. ALTER TABLE hotels ADD COLUMN coords_geo geography(Point, 4326).
  3. UPDATE coords_geo from the existing text column where parseable.
  4. CREATE INDEX gist_hotels_coords_geo on coords_geo USING GIST.
  5. Keep the old `coords` text column around for one release as a
     fallback — drop in migration 019 after API readers have migrated.

This is forward-only safe: code keeps reading the text column until a
follow-up migration removes it.

Plain CI/dev Postgres images do not ship PostGIS. In that case this
migration is a no-op; production uses infra/postgres/Dockerfile where
PostGIS is available.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    has_postgis = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis')")
    )
    if not has_postgis:
        return

    # PostGIS ships in the custom infra/postgres/Dockerfile image.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        """
        ALTER TABLE hotels
        ADD COLUMN IF NOT EXISTS coords_geo geography(Point, 4326)
        """
    )
    # Backfill from the legacy `coords` text column. Accepts both
    # "POINT(lng lat)" (PostGIS canonical text form) and plain "lng,lat".
    op.execute(
        """
        UPDATE hotels
        SET coords_geo = ST_SetSRID(
            ST_GeomFromText(
                CASE
                    WHEN coords ILIKE 'POINT(%' THEN coords
                    WHEN coords ~ '^-?[0-9]+(\\.[0-9]+)?,\\s*-?[0-9]+(\\.[0-9]+)?$' THEN
                        'POINT(' || split_part(coords, ',', 1) || ' '
                                 || trim(split_part(coords, ',', 2)) || ')'
                    ELSE NULL
                END
            ),
            4326
        )::geography
        WHERE coords IS NOT NULL AND coords_geo IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gix_hotels_coords_geo " "ON hotels USING GIST (coords_geo)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gix_hotels_coords_geo")
    op.execute("ALTER TABLE hotels DROP COLUMN IF EXISTS coords_geo")
    # Leave the PostGIS extension installed — other schemas in the same
    # database may depend on it. Operator can drop it manually if not.
