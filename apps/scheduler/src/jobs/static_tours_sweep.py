"""Periodic ingest of farvater promo buckets via `/uk/catalog/static-tours`.

This is the second farvater ingest channel — orthogonal to the price
calendar handled by `snapshot_farvater`. Where the calendar gives us
prices, this sweep gives us **operator-flagged promotion signals**
(`isHot`, `isEarly`, `IsChoiceFarvater`, `isOtp`, ...) that the May
2026 HAR investigation identified as the canonical promo carrier.

What it does, per tick:

  1. For each (bucket, country) pair → fetch all pages of static-tours
     via the production HTTP client tier (concurrency 3, 1s throttle,
     telemetry counter, breaker).
  2. Filter rows to hotels that exist in our `hotel_operator_mapping`
     for `operator='farvater'`. Unknown hotelKeys are skipped — they
     will get picked up by the next `sitemap_long_tail_ingest` pass
     which is the canonical hotel-discovery channel.
  3. Upsert into `promo_offers` with `(system_key, bucket_slug,
     observed_at)` natural key — same observed_at across all rows in
     one sweep so a re-run of the same tick is a no-op.
  4. Record a row in `scrape_runs` (source='static_tours_sweep') so
     dashboards can show throughput per bucket.

Feature flag: `FT_STATIC_TOURS_SWEEP_ENABLED` (env). Default OFF until
ops verify the first run by hand — see Sprint 1C/F risk section in the
plan file. When the flag is OFF the job logs and returns 0; when ON it
runs the full sweep.

Cadence: every 2 hours at :20. Cheap (~30-50 POSTs / run); the budget
chosen to stay gentle on the upstream even with all buckets active.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.static_tours import (
    COUNTRY_ID_EGYPT,
    COUNTRY_ID_GREECE,
    COUNTRY_ID_TURKEY,
    PromoTourRow,
    fetch_bucket_all_pages,
)
from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.farvater_http import (
    BreakerOpen,
    DailyCapHit,
    FarvaterProdClient,
    UpstreamRateLimited,
)
from src.infra.logging import get_logger
from src.services.scrape_runs import record_scrape_run

log = get_logger(__name__)


FEATURE_FLAG_ENV = "FT_STATIC_TOURS_SWEEP_ENABLED"
SCRAPE_SOURCE = "static_tours_sweep"

# (bucket_slug, country_id) pairs to sweep per tick. Starting narrow
# with Turkey + the always-present hot bucket so we can validate end-to-
# end before widening. The sweep cost grows linearly in the number of
# pairs × pages; today's matrix yields ~10 POSTs/tick.
DEFAULT_SWEEP_MATRIX: tuple[tuple[str, int], ...] = (
    ("gorjashhie-tury", COUNTRY_ID_TURKEY),
    ("gorjashhie-tury", COUNTRY_ID_EGYPT),
    ("gorjashhie-tury", COUNTRY_ID_GREECE),
    ("rannee-bronirovanie", COUNTRY_ID_TURKEY),
    ("akcionnye-tury", COUNTRY_ID_TURKEY),
)

OPERATOR_CODE = "farvater"


def _is_enabled() -> bool:
    val = os.getenv(FEATURE_FLAG_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


async def _farvater_operator_id(db: AsyncSession) -> int | None:
    row = (
        await db.execute(
            text("SELECT id FROM operators WHERE code = :c"),
            {"c": OPERATOR_CODE},
        )
    ).first()
    return int(row[0]) if row else None


async def _resolve_hotel_ids(
    db: AsyncSession, operator_id: int, hotel_keys: Iterable[int]
) -> dict[int, int]:
    """Map `farvater hotelKey -> internal hotels.id` via the existing
    `hotel_operator_mapping`. Unknown keys are simply absent from the
    returned dict — the caller drops their rows.
    """
    keys = list({str(k) for k in hotel_keys})
    if not keys:
        return {}
    rows = (
        await db.execute(
            text(
                """SELECT external_id, hotel_id
                   FROM hotel_operator_mapping
                   WHERE operator_id = :op AND external_id = ANY(:ks)"""
            ),
            {"op": operator_id, "ks": keys},
        )
    ).all()
    return {int(r.external_id): int(r.hotel_id) for r in rows}


async def _upsert_promo_offers(
    db: AsyncSession,
    *,
    observed_at: datetime,
    operator_id: int,
    hotel_key_to_id: dict[int, int],
    tours: list[PromoTourRow],
) -> int:
    """Bulk-insert promo_offers rows; return number actually written."""
    rows = []
    for t in tours:
        hid = hotel_key_to_id.get(t.hotel_key)
        if hid is None:
            # Hotel unknown — sitemap_long_tail_ingest will create it
            # in a future pass; the promo row drops here to keep FKs
            # clean. We deliberately don't auto-create hotels from the
            # static-tours response because it doesn't carry the full
            # metadata (gallery, description, etc.) sitemap_long_tail
            # captures.
            continue
        rows.append(
            {
                "observed_at": observed_at,
                "hotel_id": hid,
                "operator_id": operator_id,
                "bucket_slug": t.bucket_slug,
                "system_key": t.system_key,
                "check_in": t.check_in,
                "nights": t.nights,
                "meal_plan": t.meal_plan,
                "is_hot": t.is_hot,
                "is_early": t.is_early,
                "is_best_deal": t.is_best_deal,
                "is_recommended": t.is_recommended,
                "is_choice_farvater": t.is_choice_farvater,
                "is_otp": t.is_otp,
                "is_last_seats": t.is_last_seats,
                "is_black_friday": t.is_black_friday,
                "is_vip": t.is_vip,
                "hot_type": t.hot_type,
                "early_type": t.early_type,
                "price_uah": t.price_uah,
                "red_price_uah": t.red_price_uah,
                "promotion_end_date": t.promotion_end_date,
                "loaded_date": t.loaded_date,
                "operator_name": t.operator_name,
                "operator_id_int": t.operator_id_int,
                # JSONB stores the upstream dict so a future schema
                # change in farvater stays recoverable without re-fetch.
                "raw_payload": t.raw,
            }
        )
    if not rows:
        return 0

    # Pre-cast raw_payload to JSON because asyncpg won't bind a Python
    # dict directly into a JSON column.
    import json as _json

    for r in rows:
        r["raw_payload"] = _json.dumps(r["raw_payload"], default=str)

    # NOTE: executemany on Postgres+asyncpg returns rowcount = -1 because
    # the driver can't aggregate per-statement row counts back from the
    # batch. RETURNING doesn't help either — `.all()` on an executemany
    # result raises ResourceClosedError. So we report "attempted rows"
    # rather than "actually-inserted rows"; the natural-key index makes
    # double-counted dups impossible at the storage layer, and operators
    # can read the true count via `SELECT COUNT(*) FROM promo_offers
    # WHERE observed_at = ...` if they need exact numbers.
    await db.execute(
        text(
            """INSERT INTO promo_offers
                 (observed_at, hotel_id, operator_id, bucket_slug, system_key,
                  check_in, nights, meal_plan,
                  is_hot, is_early, is_best_deal, is_recommended,
                  is_choice_farvater, is_otp, is_last_seats, is_black_friday,
                  is_vip, hot_type, early_type,
                  price_uah, red_price_uah, promotion_end_date, loaded_date,
                  operator_name, operator_id_int, raw_payload)
               VALUES
                 (:observed_at, :hotel_id, :operator_id, :bucket_slug, :system_key,
                  :check_in, :nights, :meal_plan,
                  :is_hot, :is_early, :is_best_deal, :is_recommended,
                  :is_choice_farvater, :is_otp, :is_last_seats, :is_black_friday,
                  :is_vip, :hot_type, :early_type,
                  :price_uah, :red_price_uah, :promotion_end_date, :loaded_date,
                  :operator_name, :operator_id_int, CAST(:raw_payload AS JSON))
               ON CONFLICT (system_key, bucket_slug, observed_at) DO NOTHING"""
        ),
        rows,
    )
    # Attempted count — see comment above. Always non-negative so the
    # PROMOS_INGESTED counter stays valid.
    return len(rows)


async def _record_sweep_run(
    db: AsyncSession,
    *,
    operator_id: int | None,
    started_at: datetime,
    status: str,
    rows_inserted: int,
    error: str = "",
) -> None:
    """scrape_runs row for one sweep — mirrors `_record_run` from
    snapshot_farvater so dashboards aggregate across both."""
    await record_scrape_run(
        db,
        source=SCRAPE_SOURCE,
        status=status,
        rows_inserted=rows_inserted,
        error=error,
        started_at=started_at,
        operator_id=operator_id,
    )


async def static_tours_sweep(
    sweep_matrix: tuple[tuple[str, int], ...] = DEFAULT_SWEEP_MATRIX,
    check_in_window_days: int = 60,
) -> int:
    """Single sweep — fetch every (bucket, country) pair, upsert into
    promo_offers, record outcome. Returns rows written.

    Honours the `FT_STATIC_TOURS_SWEEP_ENABLED` feature flag. Disabled
    by default until ops verify the first run by hand.
    """
    if not _is_enabled():
        log.info("static_tours_sweep.disabled", env=FEATURE_FLAG_ENV)
        return 0

    started_at = datetime.now(UTC)
    today = started_at.date()
    check_in_to = today + timedelta(days=check_in_window_days)

    async with async_session_factory() as db:
        operator_id = await _farvater_operator_id(db)
    if operator_id is None:
        log.error("static_tours_sweep.no_operator")
        return 0

    redis = get_redis()
    total_rows = 0
    errors: list[str] = []

    try:
        async with FarvaterProdClient(redis) as client:
            for bucket, country_id in sweep_matrix:
                try:
                    tours = await fetch_bucket_all_pages(
                        client,
                        bucket_slug=bucket,
                        country_id=country_id,
                        check_in_from=today,
                        check_in_to=check_in_to,
                    )
                except (BreakerOpen, DailyCapHit) as exc:
                    # Hard stop — the rest of the sweep won't succeed
                    # either. Record what we have and bail.
                    log.warning(
                        "static_tours_sweep.aborted",
                        reason=type(exc).__name__,
                        error=str(exc),
                    )
                    errors.append(f"{type(exc).__name__}: {exc}")
                    break
                except UpstreamRateLimited as exc:
                    # Single 429 — already counted by breaker. Skip this
                    # (bucket, country) and continue.
                    log.warning(
                        "static_tours_sweep.bucket_429",
                        bucket=bucket,
                        country_id=country_id,
                        error=str(exc),
                    )
                    errors.append(f"429 {bucket}/{country_id}")
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.exception(
                        "static_tours_sweep.bucket_failed",
                        bucket=bucket,
                        country_id=country_id,
                    )
                    errors.append(f"{bucket}/{country_id}: {exc!s}")
                    continue

                if not tours:
                    log.info(
                        "static_tours_sweep.bucket_empty",
                        bucket=bucket,
                        country_id=country_id,
                    )
                    continue

                # All rows in one sweep share `observed_at` — natural
                # key dedup makes the entire sweep idempotent.
                observed_at = datetime.now(UTC).replace(microsecond=0)

                async with async_session_factory() as db:
                    hotel_keys = {t.hotel_key for t in tours}
                    mapping = await _resolve_hotel_ids(db, operator_id, hotel_keys)
                    inserted = await _upsert_promo_offers(
                        db,
                        observed_at=observed_at,
                        operator_id=operator_id,
                        hotel_key_to_id=mapping,
                        tours=tours,
                    )
                    await db.commit()

                total_rows += inserted
                # Sprint 2.1 — promo ingest visibility. The dashboard
                # panel "promos written per bucket" feeds off this counter.
                # Guard against negative inserted (shouldn't happen now that
                # we count RETURNING ids, but cheap to defend in case the
                # SQL path changes).
                if inserted > 0:
                    try:
                        from src.infra.metrics import PROMOS_INGESTED

                        PROMOS_INGESTED.labels(bucket=bucket, country=str(country_id)).inc(inserted)
                    except Exception:  # noqa: BLE001
                        log.exception("static_tours_sweep.metric_failed")
                log.info(
                    "static_tours_sweep.bucket_done",
                    bucket=bucket,
                    country_id=country_id,
                    fetched=len(tours),
                    resolved=len(mapping),
                    inserted=inserted,
                )
    except Exception as exc:  # noqa: BLE001
        log.exception("static_tours_sweep.failed")
        async with async_session_factory() as db:
            await _record_sweep_run(
                db,
                operator_id=operator_id,
                started_at=started_at,
                status="failed",
                rows_inserted=total_rows,
                error=str(exc),
            )
            await db.commit()
        return total_rows

    status = "success" if not errors else "partial"
    async with async_session_factory() as db:
        await _record_sweep_run(
            db,
            operator_id=operator_id,
            started_at=started_at,
            status=status,
            rows_inserted=total_rows,
            error="; ".join(errors)[:500],
        )
        await db.commit()

    # Stamp the staleness gauge so the StaleSnapshot alert family
    # covers this job too.
    try:
        import time as _time

        from src.infra.metrics import LAST_SUCCESSFUL_SNAPSHOT

        LAST_SUCCESSFUL_SNAPSHOT.labels(scheduled_job="static_tours_sweep").set(_time.time())
    except Exception:  # noqa: BLE001
        log.exception("static_tours_sweep.metrics_set_failed")

    log.info(
        "static_tours_sweep.done",
        rows=total_rows,
        buckets=len(sweep_matrix),
        errors=len(errors),
    )
    return total_rows
