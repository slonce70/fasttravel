# FastTravel Scheduler

Standalone APScheduler process running all periodic FastTravel jobs.
Kept separate from the FastAPI worker so heavy compute (SQL refreshes,
Telegram broadcasts) can't block API requests.

## Jobs

| Job                       | Schedule (Europe/Kyiv)   | Purpose                                                                      |
| ------------------------- | ------------------------ | ---------------------------------------------------------------------------- |
| `refresh_views`           | hourly :05               | `REFRESH MATERIALIZED VIEW CONCURRENTLY` × 3                                 |
| `detect_deals`            | hourly :10               | Strategy-loop insert into `deals` (5 methods, see below)                     |
| `notify_subscribers`      | hourly :15               | Personal Telegram alerts per filter; deepest discount, peer_anomaly ≥ 25%   |
| `snapshot_hot`            | hourly :30               | Queue high-interest hotels (read `hot:hotel:{id}` Redis counters) for live refresh |
| `refresh_worker_loop`     | continuous BRPOP         | Drains `refresh:queue` from on-demand API requests                           |
| `post_deals`              | every 15 min             | Send unposted deals to Telegram channel; sorted by `discount_pct DESC`, ≥ 15% |
| `static_tours_sweep`      | every 15 min             | Refresh `promo_offers` table from Farvater static-tours endpoint             |
| `snapshot_farvater`       | 06:00, 18:00             | Full Farvater catalog + price snapshot                                       |
| `snapshot_catalog_farvater` | 03:00                  | Cheaper catalog-only pass to discover new hotels                             |
| `decay_active_prices`     | 04:00                    | Mark stale price rows inactive (sliding 7-day window)                        |
| `refresh_baselines`       | 04:15                    | Re-compute `price_baselines` table for warm-percentile detection             |
| `cleanup_partitions`      | 04:30                    | `partman.run_maintenance_proc()` + fallback DROP                             |
| `sitemap_long_tail`       | 04:45                    | Snapshot long-tail hotels missed by the main pass                            |
| `canary_farvater_schema`  | 05:00                    | Validates upstream JSON shape; alerts on silent rename                       |

## Deal-detection strategies

`detect_deals` runs a strategy list in priority order, each consuming
remaining budget. The per-hotel cooldown prevents the same hotel from
firing across two strategies in the same tick.

| Order | `detection_method` value | Compares against | Channel? | Personal alert floor |
|---|---|---|---|---|
| 1 | `promo_discount` (was `bucket`) | operator's strike-through `red_price_uah` | ✅ | any % |
| 2 | `calendar_anomaly` (date_dip) | median of OTHER dates of same hotel/nights/meal | ✅ | any % |
| 3 | `calendar_anomaly` (stay_inversion) | shorter-stay price for same hotel/date/meal | ✅ when flag on | any % |
| 4 | `percentile` (warm) | `price_baselines.p50` per-hotel history (≥10 obs) | ✅ | any % |
| 5 | `peer_anomaly` (cold-start) | peer hotels of same destination + stars + meal + nights | ❌ | ≥ 25% only |

`peer_anomaly` is intentionally excluded from the public channel because
the baseline isn't the hotel's own normal price — it's neighbours'. UI
feed (`/api/deals`) shows everything; the `detection_method` field lets
the frontend render an explanatory subtitle per card.

## Running

Built and orchestrated via the project root `docker-compose.yml`:

```bash
docker compose up scheduler                  # tail logs
PYTHONPATH=.:.. .venv/bin/python -m pytest tests/  # 139 unit tests
docker compose run --rm scheduler pytest     # via container (slower)
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

## Cold-start mode (legacy flag)

Historical: `detect_deals` used to read the Redis key `flag:cold_start`
to force cold-only mode during the first ~30 days when `price_baselines`
was sparse. The hybrid execution model now always tries percentile +
calendar_anomaly first and fills remaining budget with peer_anomaly;
the flag still works for forced-cold testing but is no longer needed
in normal operation.

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
