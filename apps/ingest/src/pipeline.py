"""Snapshot orchestration: fetch → normalize → dedup → bulk insert.

The pipeline is the public surface of `apps/ingest` — `apps/scheduler`
imports `run_snapshot()` and nothing else.

Design notes:
  * Per-source dispatch keeps client lifecycle (context managers,
    auth setup, etc.) opaque to the caller.
  * Errors on a single hotel never abort the whole snapshot. We log,
    increment a per-source counter, and move on. The post-snapshot
    `SnapshotReport` tells the operator what fraction succeeded.
  * Bulk insert uses SQLAlchemy `insert(...).values([...])` for
    efficiency. ~3,000 rows per snapshot is a single ~10ms statement
    against Postgres on Oracle ARM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.dedup import is_duplicate, offer_fingerprint
from src.exceptions import ClientNotConfigured, IngestError, ITTourNotConfigured
from src.normalizers.base import NormalizedOffer
from src.settings import get_settings

log = structlog.get_logger()

SourceName = Literal["ittour", "farvater", "tbo"]


@dataclass(slots=True)
class HotelTarget:
    """Lightweight DTO so we don't have to import the full SQLAlchemy
    Hotel model into ingest (which would create a circular dep with
    apps/api). The scheduler caller resolves these from the DB and
    hands them in."""

    canonical_hotel_id: int
    external_id: str  # how the upstream source identifies the same hotel
    operator_code: str | None = None  # ittour returns multi-op; for farvater
    # we already know which operator's deep_link we'll get


@dataclass(slots=True)
class SnapshotReport:
    """Per-run audit. Lands in `scrape_runs` table + log line."""

    source: SourceName
    started_at: datetime
    finished_at: datetime | None = None
    hotels_processed: int = 0
    offers_collected: int = 0
    offers_inserted: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.finished_at is None:
            return "running"
        if self.errors and self.offers_inserted == 0:
            return "failed"
        if self.errors:
            return "partial"
        return "success"


async def run_snapshot(
    *,
    db: AsyncSession,
    redis: Redis,
    source: SourceName,
    hotels: list[HotelTarget],
    check_in_range: tuple[date, date],
    nights_list: list[int] | None = None,
    meal_plans: list[str] | None = None,
) -> SnapshotReport:
    """Top-level entrypoint. Caller chooses one source per invocation.

    Returns a SnapshotReport. The caller is responsible for writing it
    to `scrape_runs` (we don't import that model here — see HotelTarget).
    """
    nights_list = nights_list or [7, 10, 14]
    meal_plans = meal_plans or ["AI", "HB"]
    report = SnapshotReport(source=source, started_at=datetime.now(timezone.utc))

    try:
        collected = await _collect_offers(
            source=source,
            redis=redis,
            hotels=hotels,
            check_in_range=check_in_range,
            nights_list=nights_list,
            meal_plans=meal_plans,
            report=report,
        )
    except ClientNotConfigured as e:
        # Source is intentionally disabled (no token). Not an error per se,
        # just a no-op. The scheduler should already gate on this, but we
        # log here for the audit trail.
        log.warning("pipeline.source_skipped", source=source, reason=str(e))
        report.finished_at = datetime.now(timezone.utc)
        return report

    deduped: list[NormalizedOffer] = []
    for offer in collected:
        fp = offer_fingerprint(offer)
        if await is_duplicate(redis, fp):
            report.duplicates_skipped += 1
            continue
        deduped.append(offer)

    if deduped:
        report.offers_inserted = await _bulk_insert(db, deduped, hotels)
    report.finished_at = datetime.now(timezone.utc)

    log.info(
        "pipeline.snapshot_complete",
        source=source,
        status=report.status,
        hotels_processed=report.hotels_processed,
        offers_collected=report.offers_collected,
        offers_inserted=report.offers_inserted,
        duplicates_skipped=report.duplicates_skipped,
        errors=len(report.errors),
    )
    return report


async def _collect_offers(
    *,
    source: SourceName,
    redis: Redis,
    hotels: list[HotelTarget],
    check_in_range: tuple[date, date],
    nights_list: list[int],
    meal_plans: list[str],
    report: SnapshotReport,
) -> list[NormalizedOffer]:
    """Dispatch to the correct client + normalizer pair.

    Returns offers BEFORE deduplication.
    """
    settings = get_settings()
    collected: list[NormalizedOffer] = []

    if source == "ittour":
        if not settings.ittour_api_token:
            raise ITTourNotConfigured()
        from src.clients.ittour import ITTourClient  # local import keeps
        from src.normalizers.ittour_normalizer import parse_search_response

        async with ITTourClient() as client:
            for hotel in hotels:
                report.hotels_processed += 1
                try:
                    raw = await client.search_hotel(
                        hotel.external_id,
                        check_in_range,
                        nights_list,
                        meal_plans,
                    )
                    offers = parse_search_response(raw, hotel.external_id)
                    collected.extend(offers)
                    report.offers_collected += len(offers)
                except IngestError as e:
                    report.errors.append(f"hotel {hotel.external_id}: {e}")

    elif source == "farvater":
        # Bootstrap source. Only HTML metadata parse is wired today —
        # XHR price extraction stays a stub until HAR capture lands.
        from src.clients.farvater_scraper import FarvaterScraper
        from src.normalizers.farvater_normalizer import parse_calendar_xhr

        async with FarvaterScraper(redis) as scraper:
            for hotel in hotels:
                report.hotels_processed += 1
                try:
                    raw = await scraper.fetch_calendar_xhr(hotel.external_id)
                    offers = parse_calendar_xhr(raw)
                    collected.extend(offers)
                    report.offers_collected += len(offers)
                except (NotImplementedError, ClientNotConfigured) as e:
                    # Expected during bootstrap phase.
                    report.errors.append(f"hotel {hotel.external_id}: {e}")
                except IngestError as e:
                    report.errors.append(f"hotel {hotel.external_id}: {e}")

    elif source == "tbo":
        # TBO is content-only — does not produce price offers, only
        # NormalizedHotelContent. The caller should route TBO through
        # a separate refresh_hotel_content() entrypoint, not run_snapshot.
        raise ValueError(
            "TBO does not produce price offers — use refresh_hotel_content() instead"
        )

    else:
        raise ValueError(f"Unknown source: {source}")

    return collected


async def _bulk_insert(
    db: AsyncSession,
    offers: list[NormalizedOffer],
    hotels: list[HotelTarget],
) -> int:
    """Insert deduped offers into price_observations via raw SQL.

    We use parameterized raw SQL instead of importing the SQLAlchemy
    model from apps/api. Rationale: apps/ingest must NOT depend on
    apps/api at import time — otherwise Docker layer caching breaks
    (any change to apps/api invalidates the apps/ingest image) and
    independent test runs become impossible.
    """
    import json

    by_external = {h.external_id: h for h in hotels}
    rows: list[dict] = []
    observed_at = datetime.now(timezone.utc)
    for offer in offers:
        hotel = by_external.get(offer.hotel_external_id)
        if hotel is None:
            continue  # unknown hotel — skip silently
        rows.append({
            "observed_at": observed_at,
            "hotel_id": hotel.canonical_hotel_id,
            "check_in": offer.check_in,
            "nights": offer.nights,
            "meal_plan": offer.meal_plan,
            "room_category": offer.room_category,
            "adults": offer.adults,
            "departure_city": offer.departure_city,
            "price_uah": offer.price_uah,
            "price_original": offer.price_original,
            "currency": offer.currency,
            "fx_rate_to_uah": offer.fx_rate_to_uah,
            "deep_link": offer.deep_link,
            "raw_payload": json.dumps(offer.raw_payload),
            # operator_id is resolved later via a SQL trigger or by the
            # caller; we leave it NULL here to keep ingest decoupled from
            # the operators table.
            "operator_id": None,
        })

    if not rows:
        return 0

    stmt = text("""
        INSERT INTO price_observations (
            observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
            room_category, adults, departure_city, price_uah, price_original,
            currency, fx_rate_to_uah, deep_link, raw_payload
        ) VALUES (
            :observed_at, :hotel_id, :operator_id, :check_in, :nights, :meal_plan,
            :room_category, :adults, :departure_city, :price_uah, :price_original,
            :currency, :fx_rate_to_uah, :deep_link, CAST(:raw_payload AS jsonb)
        )
    """)
    await db.execute(stmt, rows)
    await db.commit()
    return len(rows)
