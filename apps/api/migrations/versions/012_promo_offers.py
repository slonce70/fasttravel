"""promo_offers table for operator-flagged promotions from farvater

Revision ID: 012
Revises: 011
Create Date: 2026-05-25

Sprint 1A — closes the BLOCKER finding from the May 2026 audit: until
this migration, FastTravel could only detect statistical deals
(price < p15 over 60d). HAR investigation (2026-05-25) confirmed that
operator-flagged promotions live in a different farvater endpoint
(`POST /uk/catalog/static-tours`) and carry per-row flags
(isHot, isEarly, IsChoiceFarvater, isOtp, isBestDeal, ...) whose
semantic is BUCKET MEMBERSHIP rather than column truthiness.

This table is INTENTIONALLY separate from `price_observations`:

  - promotions are tour-level events with their own lifecycle
    (LoadedDate, promotionEndDate); mixing them with the calendar
    snapshot would corrupt the percentile baselines
  - the `static_tours_sweep` job (introduced in Sprint 1C) writes here
    every 2 hours per (bucket, country) — much higher cadence than the
    calendar snapshot, and a different write pattern entirely
  - downstream promo surfaces read `promo_offers` directly via
    `/api/promotions`; `detect_deals` now remains date-dip only. Historical
    `promo_discount` deals are still render/API-supported when seeded by
    older data or manual compatibility tests.

`bucket_slug` is what encodes the promo type. We don't model isPromo
as a column because farvater's own `isPromo` field appears deprecated
(always False across 200 sampled tours in the HAR probe). The bucket
the tour was fetched from (`gorjashhie-tury`, `rannee-bronirovanie`,
`akcionnye-tury`, ...) carries the real semantic.

Boolean flags are stored alongside the bucket because farvater returns
them per-row and a tour can carry multiple flags (e.g. both `isHot`
and `IsChoiceFarvater`). Future UI surfaces may want to filter by an
individual flag rather than bucket membership.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_offers",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # `observed_at` is the time our `static_tours_sweep` job fetched
        # this row. NOT the same as `loaded_date` (when farvater itself
        # last refreshed the tour). Both kept for forensics.
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "hotel_id",
            sa.Integer,
            sa.ForeignKey("hotels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Operator may be unknown at fetch time (sweep job has the
        # farvater hotelKey but the operator-id mapping might be stale).
        # Leave nullable so we don't reject rows on a transient mapping
        # miss; reconciler job can backfill later.
        sa.Column(
            "operator_id",
            sa.Integer,
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The slug the static-tours request used. THIS is what encodes
        # the promo type. Values from HAR: 'gorjashhie-tury' (hot tours),
        # 'rannee-bronirovanie' (early booking), 'akcionnye-tury'
        # (general action). Keep as varchar so adding new buckets later
        # doesn't need a migration.
        sa.Column("bucket_slug", sa.String(32), nullable=False),
        # System key from farvater — uniquely identifies a tour offer
        # (operator + dates + room + meal combo). Joins to
        # `price_observations.raw_payload->>'systemKey'` and the deep_link
        # `?q=` param used by snapshot_farvater.
        sa.Column("system_key", sa.String(64), nullable=False),
        sa.Column("check_in", sa.Date, nullable=False),
        sa.Column("nights", sa.SmallInteger, nullable=False),
        sa.Column("meal_plan", sa.String(16), nullable=False),
        # Per-row booleans — denormalised from the static-tours JSON so
        # filters like "show only Choice Farvater" don't need to parse
        # raw_payload at query time.
        sa.Column("is_hot", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_early", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_best_deal", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_recommended", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "is_choice_farvater",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("is_otp", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_last_seats", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_black_friday", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_vip", sa.Boolean, nullable=False, server_default=sa.false()),
        # Free-form type modifiers from farvater (e.g. HotType='Last Minute').
        # Width 32 should fit observed strings comfortably.
        sa.Column("hot_type", sa.String(32), nullable=True),
        sa.Column("early_type", sa.String(32), nullable=True),
        # Pricing — keep both so we can show "was X / now Y" if farvater
        # ever starts emitting a real strike-through (today
        # red_price_uah == price_uah, but the column is the right shape).
        sa.Column("price_uah", sa.Integer, nullable=False),
        sa.Column("red_price_uah", sa.Integer, nullable=True),
        # Lifecycle from farvater. promotion_end_date drives UI "hurry,
        # ends Friday" copy and Sprint 2 freshness filters.
        sa.Column("promotion_end_date", sa.Date, nullable=True),
        sa.Column("loaded_date", sa.DateTime(timezone=True), nullable=True),
        # Operator metadata as farvater knows it. We don't FK on
        # operator_id_int because operators are managed by us, not by
        # farvater — keep this purely as upstream provenance.
        sa.Column("operator_name", sa.String(64), nullable=True),
        sa.Column("operator_id_int", sa.Integer, nullable=True),
        # Full upstream row for re-normalization without re-fetching.
        # Kept as JSONB so additions to the static-tours schema don't
        # need a migration to be captured.
        sa.Column("raw_payload", sa.JSON, nullable=True),
    )

    # Natural-key uniqueness. (system_key, bucket_slug, observed_at) so
    # the same tour can appear in multiple buckets across snapshots, but
    # within a single sweep the same (tour, bucket) only writes once.
    op.create_index(
        "uq_promo_offers_natural",
        "promo_offers",
        ["system_key", "bucket_slug", "observed_at"],
        unique=True,
    )

    # Hot path: "show me what's promoting on this hotel right now"
    # (api/hotels/{id}/promotions).
    op.create_index(
        "ix_promo_offers_hotel_observed",
        "promo_offers",
        ["hotel_id", sa.text("observed_at DESC")],
    )

    # Hot path: "show me the latest gorjashhie-tury offers" for
    # /api/promotions?bucket=...
    op.create_index(
        "ix_promo_offers_bucket_observed",
        "promo_offers",
        ["bucket_slug", sa.text("observed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_promo_offers_bucket_observed", table_name="promo_offers")
    op.drop_index("ix_promo_offers_hotel_observed", table_name="promo_offers")
    op.drop_index("uq_promo_offers_natural", table_name="promo_offers")
    op.drop_table("promo_offers")
