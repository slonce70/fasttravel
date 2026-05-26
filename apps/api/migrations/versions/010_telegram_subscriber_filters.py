"""telegram_subscriber_filters table for per-criterion bot subscriptions

Revision ID: 010
Revises: 009
Create Date: 2026-05-24

Why a separate table when `telegram_subscribers.filters_jsonb` already
exists: the bot needs to JOIN incoming `deals` rows against subscriber
filters every time a new deal lands. Doing that against a jsonb array
forces a full table scan + per-element predicate eval. A normalised
table with btree indexes on (country_iso2, max_price_uah, min_stars)
turns the match into an indexed JOIN.

One subscriber can have many filters (e.g. "TR under 40k AND EG under 60k") —
so the relationship is 1:N keyed by chat_id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_subscriber_filters",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "chat_id",
            sa.BigInteger,
            sa.ForeignKey("telegram_subscribers.chat_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("country_iso2", sa.String(2), nullable=False),
        sa.Column("max_price_uah", sa.Integer, nullable=True),
        sa.Column("min_stars", sa.SmallInteger, nullable=True),
        sa.Column("meal_plan", sa.String(8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "last_notified_deal_id",
            sa.BigInteger,
            nullable=True,
            comment="deals.id of the last alert we sent; prevents re-sending same deal",
        ),
    )
    # Match index covers the typical query in notify_subscribers:
    # WHERE is_active AND country_iso2=? AND (max_price_uah IS NULL OR price <= max_price_uah).
    op.create_index(
        "ix_tsf_active_country_price",
        "telegram_subscriber_filters",
        ["country_iso2", "is_active", "max_price_uah"],
    )
    op.create_index(
        "ix_tsf_chat_id",
        "telegram_subscriber_filters",
        ["chat_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tsf_chat_id", table_name="telegram_subscriber_filters")
    op.drop_index("ix_tsf_active_country_price", table_name="telegram_subscriber_filters")
    op.drop_table("telegram_subscriber_filters")
