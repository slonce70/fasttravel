from __future__ import annotations

import importlib
from types import SimpleNamespace


def test_telegram_claim_migration_recovers_legacy_pending_claims(monkeypatch) -> None:
    migration = importlib.import_module("migrations.versions.022_deals_telegram_claim_timestamp")
    statements: list[str] = []

    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(
            add_column=lambda *_args, **_kwargs: None,
            execute=statements.append,
        ),
    )

    migration.upgrade()

    sql = "\n".join(statements)
    assert "UPDATE deals" in sql
    assert "telegram_msg_id = -1" in sql
    assert "telegram_claimed_at IS NULL" in sql
    assert "posted_at IS NULL" in sql
