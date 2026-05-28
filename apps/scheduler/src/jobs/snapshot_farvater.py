"""Full farvater.travel ingest — discovers all hotels in all supported
countries and snapshots their price calendars.

URL / payload pattern (reverse-engineered against the production
farvater.travel HTML+XHR surface):

  catalog page:  GET  /uk/hotelscatalog/strana-{slug}/
                       → HTML containing /uk/hotel/{iso2}/{slug}/ links
  hotel page:    GET  /uk/hotel/{iso2}/{slug}/
                       → HTML; `hotelId:NNNN` in inline JS is the ittour mapKey,
                         og:image is the canonical photo, meta description is
                         a usable short description.
  prices:        POST /uk/tour/stat/low-price-calendar/auto
                       ?hotelKey={id}&adults=2&meals=all&checkIn=DD.MM.YYYY
                  body: {"dateShift":CALENDAR_DATE_SHIFT_DAYS,"nights":NIGHTS,"townFroms":"all"}
                       (NIGHTS = [7..14] — see constant below; one POST
                        returns prices for every requested night length,
                        so API load is constant in nights count)
                  → {data: {items: [{item: {night, dates: [{date, price,
                                                              priceUAH, meal,
                                                              room, systemKey}]}}]}}

Operational invariants:
  * runs as an APScheduler job inside the scheduler container
  * INSERTs are idempotent — re-running the snapshot only writes new
    observations (dedup by (hotel_id, operator_id, check_in, nights,
    meal_plan, price_uah) within the last 12h)
  * concurrency-3 per host, plus 1s spacing per worker, so we stay polite
    even when the catalog grows
  * records progress to scrape_runs so the dashboards can track success rate
  * captures ALL countries we have in destinations (TR, EG, AE, GR, ES, BG,
    ME, HR, CY, TH, MV) and ALL hotels per country (no per-country cap)
  * tries 6 check-in offsets so hotels with sparse near-term availability
    still get represented

This module is imported by src/main.py and scheduled cron('0 6,18 * * *')
in Europe/Kyiv. A standalone CLI is provided for ad-hoc runs.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients import farvater_calendar, farvater_catalog, farvater_hotel_page, farvater_runtime
from src.infra.db import async_session_factory
from src.infra.farvater_http import FarvaterProdClient
from src.infra.logging import get_logger
from src.services import hotel_upsert, price_insert, price_state, snapshot_targets
from src.services.materialized_views import refresh_price_views
from src.services.scrape_runs import record_scrape_run

log = get_logger(__name__)

_clean_description = farvater_catalog.clean_description
_clean_title = farvater_catalog.clean_title
_extract_gallery = farvater_catalog.extract_gallery
_extract_hotel_name = farvater_catalog.extract_hotel_name
_extract_stars = farvater_catalog.extract_stars
_looks_like_farvater_boilerplate = farvater_catalog.looks_like_farvater_boilerplate
_make_slug = farvater_catalog.make_slug
_name_from_url_path = farvater_catalog.name_from_url_path
_list_country_hotels = farvater_catalog.list_country_hotels
_list_sitemap_hotels = farvater_catalog.list_sitemap_hotels
_parse_jsonld = farvater_catalog.parse_jsonld
_review_from_jsonld = farvater_catalog.review_from_jsonld
HotelMeta = hotel_upsert.HotelMeta
OPERATOR_CODE = hotel_upsert.OPERATOR_CODE
_ensure_operator = hotel_upsert.ensure_operator
_country_dest_id = hotel_upsert.country_dest_id
_upsert_hotel = hotel_upsert.upsert_hotel
_upsert_mapping = hotel_upsert.upsert_mapping
PriceRow = price_insert.PriceRow
_dedup_existing = price_insert.dedup_existing
_insert_prices = price_insert.insert_prices
_mark_priced = price_state.mark_priced
_mark_unpriced = price_state.mark_unpriced
_decay_active_prices = price_state.decay_active_prices
CALENDAR_DATE_SHIFT_DAYS = farvater_calendar.CALENDAR_DATE_SHIFT_DAYS
NIGHTS = farvater_calendar.NIGHTS
_fetch_calendar = farvater_calendar.fetch_calendar
_fetch_hotel_meta = farvater_hotel_page.fetch_hotel_meta
_PRICE_REFRESH_TARGETS_SQL = snapshot_targets.PRICE_REFRESH_TARGETS_SQL
_path_from_slug = snapshot_targets.path_from_slug
_refresh_targets = snapshot_targets.refresh_targets
CATALOG_COUNTRIES = farvater_runtime.CATALOG_COUNTRIES
CHECK_IN_OFFSETS_DAYS = farvater_runtime.CHECK_IN_OFFSETS_DAYS


# ── tunables ──────────────────────────────────────────────────────────────
USER_AGENT = (
    "FastTravel-Bot/1.0 (+https://fasttravel.com.ua/about; " "snapshot 2x/day; respects robots.txt)"
)
PER_REQUEST_DELAY_S = float(os.environ.get("FT_FARVATER_REQUEST_DELAY_S", "0.0"))
CONCURRENCY = int(os.environ.get("FT_FARVATER_CONCURRENCY", "3"))
DEDUP_WINDOW_HOURS = 12
DEFAULT_MAX_HOTELS_PER_COUNTRY: int | None = None


async def _record_run(
    db: AsyncSession,
    operator_id: int,
    status: str,
    rows_inserted: int,
    error: str = "",
    started_at: datetime | None = None,
) -> None:
    await record_scrape_run(
        db,
        source="farvater_scrape",
        status=status,
        rows_inserted=rows_inserted,
        error=error,
        started_at=started_at,
        operator_id=operator_id,
    )


# ── orchestration ────────────────────────────────────────────────────────
@asynccontextmanager
async def _http_client() -> AsyncIterator[FarvaterProdClient]:
    async with farvater_runtime.open_farvater_client(default_concurrency=CONCURRENCY) as c:
        yield c


async def _process_hotel(
    client: FarvaterProdClient,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
    semaphore: asyncio.Semaphore,
    *,
    hotel_db_id: int | None = None,
) -> int:
    """Fetch one hotel's meta + calendar(s) and write them. Returns rows inserted."""
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await _fetch_hotel_meta(client, url_path, iso2)
        if meta is None:
            if hotel_db_id is not None:
                async with async_session_factory() as db:
                    await _mark_unpriced(db, hotel_db_id)
                    await db.commit()
            return 0

        # Sprint 3.5 — bail out early if a user-triggered refresh
        # (POST /api/hotels/{id}/refresh) is currently running for this
        # hotel. The 12h dedup catches the duplicate write either way,
        # but a snapshot tick that re-fetches the same hotel 100 hotels
        # later (when the user-refresh is long done) wastes a
        # farvater request and a DB roundtrip. Cheap lookup —
        # hotel_operator_mapping is indexed on (operator_id,
        # external_id).
        try:
            from src.infra.cache import get_redis

            redis = await get_redis()
            async with async_session_factory() as db:
                row = (
                    await db.execute(
                        text(
                            "SELECT hotel_id FROM hotel_operator_mapping "
                            "WHERE operator_id = :op AND external_id = :ext"
                        ),
                        {"op": operator_id, "ext": str(meta.hotel_id)},
                    )
                ).first()
            if row and await redis.exists(f"refresh:hotel:{row[0]}"):
                log.info(
                    "farvater.hotel.skipped_locked",
                    hotel_key=meta.hotel_id,
                    hotel_db_id=row[0],
                )
                return 0
        except Exception:  # noqa: BLE001 — lock check is opportunistic
            log.exception("farvater.hotel.lock_check_failed", hotel_key=meta.hotel_id)

        all_prices: list[PriceRow] = []
        seen_keys: set[str] = set()
        for offset in CHECK_IN_OFFSETS_DAYS:
            await asyncio.sleep(PER_REQUEST_DELAY_S)
            chunk = await _fetch_calendar(
                client,
                meta.hotel_id,
                check_in=date.today() + timedelta(days=offset),
            )
            new = [r for r in chunk if r.system_key not in seen_keys]
            all_prices.extend(new)
            seen_keys.update(r.system_key for r in new)

    # Write outside the semaphore to keep network slots free.
    async with async_session_factory() as db:
        hotel_db_id = await _upsert_hotel(db, meta, dest_id, operator_id)
        await _upsert_mapping(db, hotel_db_id, operator_id, meta)
        inserted = await _insert_prices(
            db, hotel_db_id, operator_id, meta, all_prices, country_iso2=iso2
        )
        # Only flip the live-prices flag when we actually wrote new rows.
        # A dedup-only pass shouldn't pretend the hotel is fresh-priced.
        if inserted > 0:
            await _mark_priced(db, hotel_db_id)
        elif not all_prices:
            await _mark_unpriced(db, hotel_db_id)
        await db.commit()
    log.info(
        "farvater.hotel.done",
        hotel=meta.name[:60],
        hotel_key=meta.hotel_id,
        calendar=len(all_prices),
        inserted=inserted,
    )
    return inserted


async def snapshot_farvater(
    *,
    max_hotels_per_country: int | None = None,
    max_runtime_minutes: int | None = None,
) -> int:
    """Top-level entrypoint. Returns total rows inserted.

    Drives the refresh from the `hotels` table (priced cohort first, then
    long tail), not from farvater's curated catalog page. See
    `_PRICE_REFRESH_TARGETS_SQL` for the ordering rationale.

    Args:
      max_hotels_per_country: optional cap for dev/testing; None = all
        active+catalogued hotels.
      max_runtime_minutes: Sprint 3.1 wall-clock budget — break the
        per-hotel loop when exceeded and record a `partial` scrape_run.
        Defaults to env `FT_SNAPSHOT_MAX_RUNTIME_MINUTES` or 0, where
        0 means unlimited for full local refills.
    """
    started_at = datetime.now(UTC)
    wall_clock_started = time.monotonic()
    if max_hotels_per_country is None:
        raw_cap = os.environ.get("FT_SNAPSHOT_MAX_HOTELS_PER_COUNTRY")
        if raw_cap:
            try:
                parsed_cap = int(raw_cap)
                max_hotels_per_country = parsed_cap if parsed_cap > 0 else None
            except ValueError:
                max_hotels_per_country = DEFAULT_MAX_HOTELS_PER_COUNTRY
        else:
            max_hotels_per_country = DEFAULT_MAX_HOTELS_PER_COUNTRY
    if max_runtime_minutes is None:
        try:
            max_runtime_minutes = int(os.environ.get("FT_SNAPSHOT_MAX_RUNTIME_MINUTES", "0"))
        except ValueError:
            max_runtime_minutes = 0
    max_runtime_s = max_runtime_minutes * 60 if max_runtime_minutes > 0 else None
    iso_filter = [iso2 for _, iso2 in CATALOG_COUNTRIES]
    log.info(
        "farvater.snapshot.start",
        countries=len(CATALOG_COUNTRIES),
        concurrency=CONCURRENCY,
        max_per_country=max_hotels_per_country,
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)
    total_inserted = 0

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    try:
        async with async_session_factory() as db:
            targets = await _refresh_targets(db, iso_filter, max_hotels_per_country)

        # Group by country for logging only — execution stays flat so a
        # single asyncio.gather can saturate the semaphore across countries.
        by_country: dict[str, int] = {}
        for _, iso2, _, _ in targets:
            by_country[iso2] = by_country.get(iso2, 0) + 1
        log.info("farvater.snapshot.targets", total=len(targets), by_country=by_country)

        async with _http_client() as client:
            # Resolve dest_id once per country to avoid round-trips per task.
            dest_ids: dict[str, int | None] = {}
            async with async_session_factory() as db:
                for iso2 in by_country:
                    dest_ids[iso2] = await _country_dest_id(db, iso2)

            tasks = [
                _process_hotel(
                    client,
                    path,
                    iso2,
                    operator_id,
                    dest_ids.get(iso2),
                    semaphore,
                    hotel_db_id=hotel_db_id,
                )
                for path, iso2, hotel_db_id, _ in targets
            ]
            # Batch the gather so a 5 000-coroutine pile doesn't sit on
            # the event loop. Each chunk also gives us periodic progress.
            chunk = 200
            partial_due_to_budget = False
            hotel_task_errors = 0
            for i in range(0, len(tasks), chunk):
                results = await asyncio.gather(*tasks[i : i + chunk], return_exceptions=True)
                inserted = sum(r for r in results if isinstance(r, int))
                errors = sum(1 for r in results if isinstance(r, Exception))
                hotel_task_errors += errors
                total_inserted += inserted
                log.info(
                    "farvater.snapshot.progress",
                    processed=i + len(results),
                    of=len(tasks),
                    inserted=inserted,
                    errors=errors,
                    cumulative_inserted=total_inserted,
                )
                # Sprint 3.1 — wall-clock budget. Coroutines already
                # in-flight in the next chunk get cancelled by the
                # outer task scope when we break.
                if (
                    max_runtime_s is not None
                    and time.monotonic() - wall_clock_started > max_runtime_s
                ):
                    log.warning(
                        "farvater.snapshot.wall_clock_budget_exhausted",
                        budget_minutes=max_runtime_minutes,
                        processed=i + len(results),
                        of=len(tasks),
                        cumulative_inserted=total_inserted,
                    )
                    partial_due_to_budget = True
                    break

        # Skip MV refresh on partial snapshots — incomplete data would
        # make the MVs reflect a subset of the catalog. The hourly
        # refresh_views job (:05) picks up the slack on the next tick.
        partial_due_to_errors = hotel_task_errors > 0
        if not partial_due_to_budget and not partial_due_to_errors:
            await refresh_price_views(log_prefix="farvater.snapshot")
        else:
            reason = "partial_snapshot_errors" if partial_due_to_errors else "partial_snapshot"
            log.info(
                "farvater.snapshot.mv_refresh_skipped",
                reason=reason,
            )
        # Decay moved to its own daily job (`decay_active_prices`, 04:00
        # Kyiv) so a snapshot failure doesn't leave stale hotels in /search.
        # See Sprint 1F in the plan file.

        # Surface how often one tuple has multiple room categories in the
        # last 24h. Since migration 020 current_prices preserves these rows;
        # this metric now tracks how much room-level variety the detector sees.
        try:
            async with async_session_factory() as db:
                collapsed = (
                    await db.execute(
                        text(
                            """SELECT COUNT(*) FROM (
                                   SELECT 1
                                   FROM price_observations
                                   WHERE observed_at >= NOW() - INTERVAL '24 hours'
                                   GROUP BY hotel_id, operator_id, check_in,
                                            nights, meal_plan
                                   HAVING COUNT(DISTINCT room_category) > 1
                               ) t"""
                        )
                    )
                ).scalar() or 0
            from src.infra.metrics import ROOMS_COLLAPSED_LAST_REFRESH

            ROOMS_COLLAPSED_LAST_REFRESH.set(int(collapsed))
            log.info("farvater.snapshot.room_variants", count=int(collapsed))
        except Exception:  # noqa: BLE001 — diagnostic must never fail the job
            log.exception("farvater.snapshot.rooms_collapsed_probe_failed")

        run_status = "partial" if partial_due_to_budget or partial_due_to_errors else "success"
        run_errors: list[str] = []
        if partial_due_to_budget:
            run_errors.append(f"wall_clock_budget_exhausted ({max_runtime_minutes}m)")
        if partial_due_to_errors:
            run_errors.append(f"hotel_task_errors={hotel_task_errors}")
        run_error = "; ".join(run_errors)
        async with async_session_factory() as db:
            await _record_run(
                db,
                operator_id,
                run_status,
                total_inserted,
                error=run_error,
                started_at=started_at,
            )
            await db.commit()
        # Stamp the per-job staleness gauge so Prometheus can alert when
        # a snapshot is overdue. Set ONLY on success; failures leave the
        # last successful timestamp in place, which is what the alert
        # rule (`StaleSnapshot`) actually wants.
        if run_status == "success":
            try:
                from src.infra.metrics import LAST_SUCCESSFUL_SNAPSHOT

                LAST_SUCCESSFUL_SNAPSHOT.labels(scheduled_job="snapshot_farvater").set(time.time())
            except Exception:  # noqa: BLE001 — metrics must never crash a job
                log.exception("farvater.snapshot.metrics_set_failed")
        log.info("farvater.snapshot.done", inserted=total_inserted)
        return total_inserted

    except Exception as exc:
        async with async_session_factory() as db:
            await _record_run(
                db, operator_id, "failed", total_inserted, error=str(exc), started_at=started_at
            )
            await db.commit()
        log.error("farvater.snapshot.failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(snapshot_farvater(max_hotels_per_country=cap))
