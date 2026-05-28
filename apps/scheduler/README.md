# FastTravel Scheduler

Standalone APScheduler process running all periodic FastTravel jobs.
Kept separate from the FastAPI worker so heavy compute (SQL refreshes,
Telegram broadcasts) can't block API requests.

## Jobs

| Job                       | Schedule (Europe/Kyiv)   | Purpose                                                                      |
| ------------------------- | ------------------------ | ---------------------------------------------------------------------------- |
| `refresh_views`           | hourly :05               | `REFRESH MATERIALIZED VIEW CONCURRENTLY` × 3                                 |
| `detect_deals`            | hourly :10               | Insert same-hotel date-dip deals and real operator promo discounts            |
| `notify_subscribers`      | hourly :15               | Personal Telegram alerts per filter; deepest discount, peer_anomaly ≥ 25%   |
| `snapshot_hot`            | hourly :30               | Queue high-interest hotels (read `hot:hotel:{id}` Redis counters) for live refresh |
| `refresh_worker_loop`     | continuous BRPOP         | Drains `refresh:queue` from on-demand API requests                           |
| `post_deals`              | every 15 min             | Send unposted deals to Telegram channel; sorted by `discount_pct DESC`, ≥ 4% |
| `static_tours_sweep`      | every 15 min             | Refresh `promo_offers` table from Farvater static-tours endpoint             |
| `snapshot_farvater`       | 06:00, 18:00             | Full Farvater catalog + price snapshot                                       |
| `snapshot_catalog_farvater` | 03:00                  | Cheaper catalog-only pass to discover new hotels                             |
| `decay_active_prices`     | 04:00                    | Mark stale price rows inactive (sliding 7-day window)                        |
| `refresh_baselines`       | 04:15                    | Re-compute legacy `price_baselines` for analysis/historical compatibility    |
| `cleanup_partitions`      | 04:30                    | `partman.run_maintenance_proc()` + fallback DROP                             |
| `sitemap_long_tail`       | 04:45                    | Snapshot long-tail hotels missed by the main pass                            |
| `canary_farvater_schema`  | 05:00                    | Validates upstream JSON shape; alerts on silent rename                       |

## Deal-detection strategies

`detect_deals` currently runs two production strategies. The primary one,
`date_dip`, compares each current offer with nearby check-in dates for the
same hotel, operator, nights, meal plan, and materialized
room-family/quality/view bucket. This keeps the public "neighboring dates"
copy aligned with the SQL. The secondary one promotes only real Farvater
strike-through promos where `red_price_uah > price_uah`; bucket-only promo
flags stay in `/api/promotions`.

| Active | `detection_method` value | Compares against | Channel? | Personal alert floor |
|---|---|---|---|---|
| yes | `calendar_anomaly` (date_dip) | trimmed local baseline of nearby dates for same hotel/operator/nights/meal/room-family-quality-view bucket | ✅ | ≥ 4% |
| yes | `promo_discount` | operator-provided red price from `promo_offers.red_price_uah` | ✅ | ≥ 4% |

The shared policy is `DATE_DIP_POLICY` in `apps/shared/deal_detection.py`.
Current thresholds are: check-in 5-90 days out, neighbour window ±14 days,
at least 4 comparable neighbouring dates, max neighbour spread 2.5x, strict
0.96 baseline multiplier, and at least 1500 UAH absolute saving.

Historical rows may still contain `percentile` or `peer_anomaly`; those
values remain supported by API/web/bot renderers so older deals explain
themselves correctly. `peer_anomaly` stays excluded from the public channel
because its baseline is neighbouring hotels, not the hotel's own normal
price. UI feed (`/api/deals`) can still show it with a distinct subtitle.

Personal alerts use a per-filter notification ledger
(`telegram_filter_notifications`) for idempotency. This keeps the
documented deepest-discount ordering without letting a single
`last_notified_deal_id` cursor hide lower-id deals that still match a
subscriber filter. They use the same 6-hour freshness window as public channel
posts, so downtime recovery does not send old price signals.

## Running

Built and orchestrated via the project root `docker-compose.yml`:

```bash
docker compose up scheduler                         # tail logs
PYTHONPATH=.:.. .venv/bin/python -m pytest tests/   # scheduler tests
docker compose build scheduler && docker compose up -d scheduler
```

DB-backed SQL selection checks live under `tests/integration/`. They skip
when no usable Postgres is configured locally; to force the same network path
as CI/compose:

```bash
docker compose up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.test.yml build api-test scheduler-test
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps scheduler-test pytest tests/integration/ -q
```

## Cross-package dependencies

- `apps/scheduler/src/jobs/{post_deals,notify_subscribers}.py` use the
  shared Telegram publisher from `apps/shared/publishers/broadcast.py`
  (`make_bot`, `broadcast_deal`, `escape_markdown_v2`).
- `src/config.py` inherits `BaseAppSettings` from
  `apps/shared/infra/base_settings.py`; service-specific Telegram knobs
  and `_extra_prod_offenders()` stay local.
- `src/infra/logging.py` and `src/infra/sentry.py` are thin wrappers
  over `apps/shared/infra/` so renderer / integration drift between
  api/bot/scheduler can't happen again (audit Sprint #7).

The Docker image uses build context `./apps` so `shared/` ends up at
`/app/shared/` inside the container alongside `src/`.

## Legacy detector flags

Historical: `detect_deals` used to read Redis feature flags for cold-start
peer comparisons and stay-inversion experiments. The production detector no
longer reads those flags; use the current `date_dip` path for local smoke
runs and treat stale Redis keys as inert.

## Graceful no-token mode

If `TELEGRAM_BOT_TOKEN` is empty (typical in dev), `post_deals` logs a
skipped event and returns. The rest of the scheduler keeps running.

In `ENVIRONMENT=prod`, `Settings.assert_prod_secrets()` refuses to boot
when `DEALS_DAILY_CAP > 0` and either `TELEGRAM_BOT_TOKEN` or
`TELEGRAM_CHANNEL_ID` is missing.

## Observability

- Prometheus `/metrics` on `:9101` (counters per job + queue depth +
  Farvater HTTP breaker state).
- 9 alert rules in `infra/prometheus/rules/fasttravel.yml` cover:
  stale snapshot, no deals detected, breaker tripped, refresh-queue
  backlog, disk full > 80%, OOM risk, postgres dead tuples, redis down,
  stale catalog snapshot.
