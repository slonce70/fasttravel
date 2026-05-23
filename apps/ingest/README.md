# apps/ingest

Data ingestion library. **Not a runnable service** — imported by `apps/scheduler` to fetch prices and hotel content from upstream sources.

## Sources

| Source | Type | Status | Notes |
|---|---|---|---|
| **ittour** | JSON API (token) | ⏳ waiting partner agreement | Primary source. See `docs/outreach/01-ittour.md`. Endpoints are speculative until token + docs arrive. |
| **farvater scraper** | HTML/XHR (no token) | 🟡 bootstrap-only | Conservative client (0.5 req/sec, 1k/day cap, circuit breaker). Calendar XHR endpoint TBD (manual HAR capture required). |
| **TBO Holidays** | JSON API (basic auth) | ⏳ waiting free account | Hotel content only (photos, descriptions, GPS) — no tour prices. See `docs/outreach/02-tbo-holidays.md`. |

## Architecture

```
apps/scheduler.jobs.snapshot_hot.py
        │
        ▼
apps/ingest.pipeline.run_snapshot(source="ittour", hotels=[...], ...)
        │
        ├── clients/ittour.py        ──► raw response
        │   normalizers/ittour_normalizer.py ──► NormalizedOffer[]
        │
        ├── dedup.py (Redis fingerprint)
        │
        └── _bulk_insert(db, offers, hotels)  ──► price_observations table
```

## How to add a new source

1. Subclass `BaseClient` in `src/clients/<name>.py`. Override `source`, `base_url`, `_default_headers()`.
2. Write `src/normalizers/<name>_normalizer.py` that returns `list[NormalizedOffer]`.
3. Add a dispatch branch in `pipeline._collect_offers()`.
4. Add a VCR fixture in `tests/fixtures/<name>_sample.yaml` and a normalizer unit test.

## Local testing

```bash
# Tests use VCR cassettes — no real network calls.
docker compose run --rm scheduler pytest apps/ingest/tests/

# Smoke test the pipeline against the demo seed data:
docker compose run --rm scheduler python -c "
import asyncio
from apps.ingest.src.pipeline import run_snapshot, HotelTarget
# ... (TODO: small smoke harness, write after seed_demo finalized)
"
```

## Operational notes

- **farvater circuit breaker:** trips on 3 consecutive 429/403 within 10 minutes, stays open for 1 hour. State lives in Redis (`ingest:farvater:breaker:open_until`).
- **Daily cap:** 1000 requests/day, counter in Redis with TTL until UTC midnight.
- **Dedup window:** 12 hours by default (`DEDUP_TTL_HOURS` env var). Identical fingerprint within that window → skip.
- **Graceful skip:** if a source's token is empty, `ClientNotConfigured` is raised; the scheduler logs `skipped_no_token` and moves on. No retries.

## What this layer does NOT do

- **No business logic** (deal detection, ranking) — that's `apps/scheduler.jobs.detect_deals`.
- **No HTTP serving** — that's `apps/api`.
- **No Telegram** — that's `apps/scheduler.jobs.post_deals` + `apps/bot.publishers.broadcast`.
- **No browser-rendered scraping.** If a source's prices require JavaScript, we either find an XHR endpoint or wait for an official API.
