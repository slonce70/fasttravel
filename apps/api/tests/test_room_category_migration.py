from __future__ import annotations

import importlib


def test_current_prices_room_category_is_part_of_latest_mv_key(monkeypatch) -> None:
    migration = importlib.import_module("migrations.versions.020_room_category_current_prices")
    statements: list[str] = []

    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._create_current_prices(include_room=True)

    sql = "\n".join(statements)

    assert (
        "SELECT DISTINCT ON (hotel_id, operator_id, check_in, nights, meal_plan, room_category)"
        in sql
    )
    assert (
        "ORDER BY hotel_id, operator_id, check_in, nights, meal_plan, room_category, "
        "observed_at DESC"
    ) in sql
    assert (
        "ON current_prices (hotel_id, operator_id, check_in, nights, meal_plan, room_category)"
        in sql
    )
    assert "CREATE INDEX IF NOT EXISTS idx_current_prices_date_dip_lookup" in sql
    assert (
        "ON current_prices (hotel_id, operator_id, nights, meal_plan, room_category, check_in)"
        in sql
    )


def test_room_category_migration_rebuilds_observation_key_and_calendar_mv(monkeypatch) -> None:
    migration = importlib.import_module("migrations.versions.020_room_category_current_prices")
    statements: list[str] = []

    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = "\n".join(statements)

    assert migration.down_revision == "019"
    assert "DROP MATERIALIZED VIEW IF EXISTS current_prices CASCADE" in sql
    assert "ALTER TABLE price_observations ALTER COLUMN room_category SET DEFAULT ''" in sql
    assert "UPDATE price_observations SET room_category = '' WHERE room_category IS NULL" in sql
    assert "ALTER TABLE price_observations ALTER COLUMN room_category SET NOT NULL" in sql
    assert "DROP INDEX IF EXISTS uq_price_obs_natural" in sql
    assert "meal_plan, room_category, observed_at" in sql
    assert "CREATE MATERIALIZED VIEW hotel_calendar_prices" in sql
