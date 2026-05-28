"""Shared scrape_runs recording helper for scheduler jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text


async def record_scrape_run(
    db: Any,
    *,
    source: str,
    status: str,
    rows_inserted: int = 0,
    error: str = "",
    started_at: datetime | None = None,
    operator_id: int | None = None,
) -> None:
    """Insert one scrape_runs row without owning the transaction."""
    await db.execute(
        text(
            """INSERT INTO scrape_runs
                 (started_at, finished_at, operator_id, source, status,
                  rows_inserted, error_text)
               VALUES (:s, NOW(), :op, :src, :st, :n, :e)"""
        ),
        {
            "s": started_at or datetime.now(UTC),
            "op": operator_id,
            "src": source,
            "st": status,
            "n": rows_inserted,
            "e": error[:500],
        },
    )
