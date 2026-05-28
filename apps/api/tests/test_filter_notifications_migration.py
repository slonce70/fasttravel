from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, Protocol, cast


class _Migration019(Protocol):
    op: Any

    def upgrade(self) -> None: ...


def test_filter_notification_migration_is_self_contained() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "019_telegram_filter_notifications.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    disallowed_roots = {"apps", "shared", "src"}
    import_roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_roots.append(node.module.split(".", 1)[0])

    assert disallowed_roots.isdisjoint(import_roots)
    assert "sys.path" not in source


def test_filter_notification_backfill_matches_canonical_meal_filters() -> None:
    migration = cast(
        _Migration019,
        importlib.import_module("migrations.versions.019_telegram_filter_notifications"),
    )
    executed: list[str] = []

    class FakeOp:
        def create_table(self, *args: object, **kwargs: object) -> None:
            return None

        def create_index(self, *args: object, **kwargs: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            executed.append(sql)

    old_op = migration.op
    migration.op = FakeOp()
    try:
        migration.upgrade()
    finally:
        migration.op = old_op

    backfill_sql = "\n".join(executed)
    assert "INSERT INTO telegram_filter_notifications" in backfill_sql
    assert "d.id <= f.last_notified_deal_id" in backfill_sql
    assert "d.detected_at >= NOW() - INTERVAL '24 hours'" in backfill_sql
    assert "f.is_active" in backfill_sql
    assert "dest.country_iso2 = f.country_iso2" in backfill_sql
    assert "(f.max_price_uah IS NULL OR d.price_uah <= f.max_price_uah)" in backfill_sql
    assert "(f.min_stars IS NULL OR h.stars >= f.min_stars)" in backfill_sql
    assert "f.meal_plan IS NULL" in backfill_sql
    assert "d.meal_plan = f.meal_plan" in backfill_sql
    assert "f.meal_plan = 'all_inclusive'" in backfill_sql
    assert "d.meal_plan IN ('AI', 'UAI')" in backfill_sql
    assert "f.meal_plan = 'half_board'" in backfill_sql
    assert "d.meal_plan IN ('HB')" in backfill_sql
    assert "f.meal_plan = 'breakfast'" in backfill_sql
    assert "d.meal_plan IN ('BB')" in backfill_sql
    assert "f.meal_plan = 'room_only'" in backfill_sql
    assert "d.meal_plan IN ('RO')" in backfill_sql
    assert "f.meal_plan = 'full_board'" in backfill_sql
    assert "d.meal_plan IN ('FB')" in backfill_sql
    assert "ON CONFLICT DO NOTHING" in backfill_sql
