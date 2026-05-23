"""Drop price_observations partitions older than the retention window.

Strategy (in order of preference):

1. Configure pg_partman 5.x to retain ``retention_days`` and call
   ``partman.run_maintenance_proc()``. This is idempotent — re-running
   the UPDATE is a no-op once the config is set.

2. If pg_partman isn't available (local dev without the extension), fall
   back to a raw scan of ``information_schema.tables`` for
   ``price_observations_p%`` whose date suffix is older than the
   retention window, and ``DROP TABLE`` them.

Migration 001 created partitions but did NOT configure retention. We do
the UPSERT here rather than in a separate migration so the policy lives
next to the job that uses it — if you change retention, only this file
changes.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.config import get_settings
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


_CONFIGURE_RETENTION = text(
    """
    UPDATE partman.part_config
    SET retention = :retention_interval,
        retention_keep_table = false,
        infinite_time_partitions = true
    WHERE parent_table = 'public.price_observations'
    """
)

_RUN_MAINTENANCE = text("CALL partman.run_maintenance_proc()")

# Fallback: enumerate child partitions and drop those whose name suffix
# (pg_partman naming convention: parent_pYYYY_MM_DD) is older than the
# retention cutoff. partman names by partition *start*, so a week-partition
# named price_observations_p2026_01_05 covers Jan 5–12 — comparing start to
# (today - retention) gives a conservative-correct DROP set.
_FALLBACK_LIST_OLD = text(
    """
    SELECT child.relname AS partition_name
    FROM pg_inherits i
    JOIN pg_class parent ON i.inhparent = parent.oid
    JOIN pg_class child  ON i.inhrelid  = child.oid
    WHERE parent.relname = 'price_observations'
      AND child.relname  ~ '^price_observations_p[0-9_]+$'
      AND to_date(
            substring(child.relname FROM 'p([0-9_]+)$'),
            'YYYY_MM_DD'
          ) < (CURRENT_DATE - (:retention_days || ' days')::interval)
    """
)


async def cleanup_partitions() -> None:
    settings = get_settings()
    retention_days = settings.partition_retention_days
    retention_interval = f"{retention_days} days"

    # --- Try pg_partman path ---
    try:
        async with async_session_factory() as db:
            await db.execute(
                _CONFIGURE_RETENTION,
                {"retention_interval": retention_interval},
            )
            await db.execute(_RUN_MAINTENANCE)
            await db.commit()
        log.info(
            "partitions.cleaned",
            method="pg_partman",
            retention_days=retention_days,
        )
        return
    except DBAPIError as exc:
        # The two realistic failure modes: extension missing (function not
        # found) OR procedure-permissions issue. Either way, fall through
        # to the raw-DROP path so partitions still get GC'd.
        log.warning(
            "partitions.partman_unavailable",
            error=str(exc.orig) if exc.orig else str(exc),
            note="falling back to raw DROP TABLE scan",
        )

    # --- Fallback raw DROP path ---
    async with async_session_factory() as db:
        result = await db.execute(
            _FALLBACK_LIST_OLD, {"retention_days": retention_days}
        )
        names = [r.partition_name for r in result]
        for name in names:
            # Cannot parametrise table identifiers in libpq — names came
            # from pg_class with a strict regex above, so safe to inline.
            await db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await db.commit()

    log.info(
        "partitions.cleaned",
        method="raw_drop",
        retention_days=retention_days,
        dropped=len(names),
        names=names,
    )
