"""deals.detection_method — separate "why was this a deal?" from "what feed?"

Revision ID: 013
Revises: 012
Create Date: 2026-05-25

Existing `deals.source` (added in 004) tracks upstream provenance
('farvater_scrape' | 'live_refresh' | 'ittour' | NULL). It answers
"which ingest pipeline produced the underlying price?". It does NOT
answer "why did detect_deals flag this row?". Those are different
dimensions, and the May 2026 audit caught us conflating them.

This migration adds `detection_method` for the "why":
  - 'percentile'         — existing warm/cold percentile rule
  - 'bucket_<slug>'      — promo_offers branch (e.g. 'bucket_gorjashhie-tury')
                           introduced in Sprint 1D
  - 'peer_anomaly'       — future Phase 2 ML detector

Default = 'percentile' so historical deals (all detected before this
migration ships) get the right value retroactively.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column(
            "detection_method",
            sa.String(64),
            nullable=False,
            server_default="percentile",
        ),
    )
    # Hot path: "list current bucket-based promo deals" for
    # /api/promotions and Telegram broadcaster filtering.
    op.create_index(
        "ix_deals_detection_method",
        "deals",
        ["detection_method", sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_deals_detection_method", table_name="deals")
    op.drop_column("deals", "detection_method")
