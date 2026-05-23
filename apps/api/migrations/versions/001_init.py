"""init: full FastTravel schema

Revision ID: 001
Revises:
Create Date: 2026-05-23

Creates every table, partition setup, materialized view and index defined
in the project plan. Extensions (pg_trgm, btree_gin, pg_cron, pg_partman)
are bootstrapped by infra/postgres/init-extensions.sh on first cluster
init, so this migration only depends on them existing.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Safety net: extensions may already exist (from init-extensions.sh)
    # but if a developer drops the DB and re-runs migrations on a cluster
    # that already had them loaded, IF NOT EXISTS keeps us idempotent.
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # ----- operators ----------------------------------------------------
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("affiliate_url_template", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ----- destinations -------------------------------------------------
    op.create_table(
        "destinations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("country_iso2", sa.CHAR(2), nullable=False),
        sa.Column("region_slug", sa.String(64), nullable=False),
        sa.Column("name_uk", sa.String(128), nullable=False),
        sa.Column("name_en", sa.String(128), nullable=True),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("destinations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("country_iso2", "region_slug", name="uq_destinations_country_region"),
    )

    # ----- hotels -------------------------------------------------------
    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("canonical_slug", sa.String(160), nullable=False, unique=True),
        sa.Column("name_uk", sa.String(256), nullable=False),
        sa.Column("name_en", sa.String(256), nullable=True),
        sa.Column("stars", sa.SmallInteger, nullable=True),
        sa.Column(
            "destination_id",
            sa.Integer,
            sa.ForeignKey("destinations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # We use Postgres' built-in `point` type. No spatial index for MVP;
        # migrate to PostGIS + GIST when proximity search is needed.
        sa.Column("coords", sa.dialects.postgresql.TEXT, nullable=True),
        sa.Column("tbo_code", sa.String(64), nullable=True),
        sa.Column("giata_code", sa.String(64), nullable=True),
        sa.Column("description_uk", sa.Text, nullable=True),
        sa.Column("photos_jsonb", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("amenities", sa.dialects.postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("review_score", sa.Numeric(3, 1), nullable=True),
        sa.Column("review_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name="stars_range"),
    )

    # Promote the column to native `point` (the ORM keeps it as TEXT for
    # portability; we store it as `point` for future PostGIS migration).
    op.execute("ALTER TABLE hotels ALTER COLUMN coords TYPE point USING coords::point")

    op.create_index(
        "ix_hotels_destination_id",
        "hotels",
        ["destination_id"],
        postgresql_where=sa.text("is_active"),
    )
    op.execute(
        "CREATE INDEX ix_hotels_name_uk_trgm ON hotels USING gin (name_uk gin_trgm_ops)"
    )

    # ----- hotel_operator_mapping --------------------------------------
    op.create_table(
        "hotel_operator_mapping",
        sa.Column(
            "operator_id",
            sa.Integer,
            sa.ForeignKey("operators.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("external_id", sa.String(64), primary_key=True),
        sa.Column(
            "hotel_id",
            sa.Integer,
            sa.ForeignKey("hotels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_name", sa.String(256), nullable=True),
    )
    op.create_index(
        "ix_hotel_operator_mapping_hotel_id",
        "hotel_operator_mapping",
        ["hotel_id"],
    )

    # ----- price_observations (partitioned parent table) ----------------
    # SQLAlchemy 2.x emits PARTITION BY when we pass postgresql_partition_by
    # as a table option. We must include observed_at in the PK.
    op.execute(
        """
        CREATE TABLE price_observations (
            id              BIGSERIAL,
            observed_at     TIMESTAMPTZ NOT NULL,
            hotel_id        INTEGER NOT NULL REFERENCES hotels(id) ON DELETE CASCADE,
            operator_id     INTEGER NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
            check_in        DATE NOT NULL,
            nights          SMALLINT NOT NULL,
            meal_plan       VARCHAR(16) NOT NULL,
            room_category   VARCHAR(64),
            adults          SMALLINT NOT NULL DEFAULT 2,
            departure_city  VARCHAR(32),
            price_uah       INTEGER NOT NULL,
            price_original  INTEGER,
            currency        CHAR(3) NOT NULL DEFAULT 'UAH',
            fx_rate_to_uah  NUMERIC(10,4),
            deep_link       TEXT,
            raw_payload     JSONB,
            PRIMARY KEY (id, observed_at)
        ) PARTITION BY RANGE (observed_at);
        """
    )

    # Hand control of partitioning to pg_partman 5.x.
    # API change vs 4.x:
    #   - `partman.create_parent` (not `public.create_parent`)
    #   - p_interval is a string interval like '1 week'
    #   - p_type defaults to 'range' in 5.x
    op.execute(
        """
        SELECT partman.create_parent(
            p_parent_table  := 'public.price_observations',
            p_control       := 'observed_at',
            p_interval      := '1 week',
            p_premake       := 4
        );
        """
    )

    # Indexes are inherited by all child partitions automatically.
    op.execute(
        """
        CREATE INDEX ix_price_obs_calendar
        ON price_observations (hotel_id, check_in, nights, meal_plan, observed_at DESC);
        """
    )
    # NOTE: original plan had `WHERE check_in >= CURRENT_DATE` here.
    # Postgres rejects that — partial-index predicates must be IMMUTABLE
    # and CURRENT_DATE is STABLE. The deal-detection cron applies the
    # date filter at query time; the index still serves both reads
    # efficiently because it leads with observed_at.
    op.execute(
        """
        CREATE INDEX ix_price_obs_deal_window
        ON price_observations (observed_at, check_in);
        """
    )

    # ----- deals --------------------------------------------------------
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "hotel_id",
            sa.Integer,
            sa.ForeignKey("hotels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operator_id",
            sa.Integer,
            sa.ForeignKey("operators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_in", sa.Date, nullable=False),
        sa.Column("nights", sa.SmallInteger, nullable=False),
        sa.Column("meal_plan", sa.String(16), nullable=False),
        sa.Column("price_uah", sa.Integer, nullable=False),
        sa.Column("baseline_p50", sa.Integer, nullable=False),
        sa.Column("discount_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("deep_link", sa.Text, nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_msg_id", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_deals_hotel_id", "deals", ["hotel_id"])
    op.execute(
        """
        CREATE INDEX ix_deals_unposted
        ON deals (detected_at)
        WHERE posted_at IS NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX ix_deals_posted
        ON deals (posted_at DESC)
        WHERE posted_at IS NOT NULL;
        """
    )

    # ----- telegram_subscribers ----------------------------------------
    op.create_table(
        "telegram_subscribers",
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_active",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "filters_jsonb",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_blocked", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )

    # ----- scrape_runs --------------------------------------------------
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "operator_id",
            sa.Integer,
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows_inserted", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_text", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # Materialised views.  All created WITH NO DATA; the first populated
    # refresh must be NON-CONCURRENT (CONCURRENTLY requires existing rows
    # AND a unique index, but Postgres also refuses CONCURRENTLY on a
    # never-populated MV).  See README for the priming command.
    # ------------------------------------------------------------------

    # --- current_prices: latest snapshot per (hotel, operator, config) ---
    op.execute(
        """
        CREATE MATERIALIZED VIEW current_prices AS
        SELECT DISTINCT ON (hotel_id, operator_id, check_in, nights, meal_plan)
            hotel_id,
            operator_id,
            check_in,
            nights,
            meal_plan,
            room_category,
            price_uah,
            price_original,
            currency,
            deep_link,
            observed_at
        FROM price_observations
        WHERE check_in >= CURRENT_DATE
          AND check_in <= CURRENT_DATE + INTERVAL '90 days'
        ORDER BY hotel_id, operator_id, check_in, nights, meal_plan, observed_at DESC
        WITH NO DATA;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_current_prices_key
        ON current_prices (hotel_id, operator_id, check_in, nights, meal_plan);
        """
    )

    # --- hotel_calendar_prices: per-day min plus per-night-bucket mins ---
    # NOTE: the original plan said "MIN(price) GROUP BY (hotel, check_in)".
    # We expand it with conditional aggregates so the calendar endpoint
    # can return separate heatmaps for 7n/10n/14n without a second query.
    op.execute(
        """
        CREATE MATERIALIZED VIEW hotel_calendar_prices AS
        SELECT
            hotel_id,
            check_in,
            MIN(price_uah)                                            AS min_price_uah,
            MIN(price_uah) FILTER (WHERE nights = 7)                  AS min_7n,
            MIN(price_uah) FILTER (WHERE nights = 10)                 AS min_10n,
            MIN(price_uah) FILTER (WHERE nights = 14)                 AS min_14n,
            MAX(observed_at)                                          AS last_observed_at
        FROM current_prices
        GROUP BY hotel_id, check_in
        WITH NO DATA;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_hotel_calendar_prices_key
        ON hotel_calendar_prices (hotel_id, check_in);
        """
    )

    # --- price_baselines: p15/p50/p85 over 60-day rolling window ---
    op.execute(
        """
        CREATE MATERIALIZED VIEW price_baselines AS
        SELECT
            hotel_id,
            nights,
            meal_plan,
            EXTRACT(MONTH FROM check_in)::SMALLINT             AS check_in_month,
            COUNT(*)                                           AS observation_count,
            percentile_disc(0.15) WITHIN GROUP (ORDER BY price_uah)::INTEGER AS p15,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY price_uah)::INTEGER AS p50,
            percentile_disc(0.85) WITHIN GROUP (ORDER BY price_uah)::INTEGER AS p85
        FROM price_observations
        WHERE observed_at >= NOW() - INTERVAL '60 days'
        GROUP BY hotel_id, nights, meal_plan, EXTRACT(MONTH FROM check_in)
        WITH NO DATA;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_price_baselines_key
        ON price_baselines (hotel_id, nights, meal_plan, check_in_month);
        """
    )


def downgrade() -> None:
    # MVs first (depend on price_observations)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS price_baselines")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS hotel_calendar_prices")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices")

    # Detach partman bookkeeping before dropping the parent.
    op.execute(
        "DELETE FROM partman.part_config WHERE parent_table = 'public.price_observations'"
    )
    op.execute("DROP TABLE IF EXISTS price_observations CASCADE")

    op.drop_table("scrape_runs")
    op.drop_table("telegram_subscribers")
    op.drop_table("deals")
    op.drop_table("hotel_operator_mapping")
    op.drop_table("hotels")
    op.drop_table("destinations")
    op.drop_table("operators")
