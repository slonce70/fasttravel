# FastTravel Scheduler

Standalone APScheduler process running all periodic FastTravel jobs.
Kept separate from the FastAPI worker so heavy compute (SQL refreshes,
Telegram broadcasts) can't block API requests.

## Jobs

| Job                  | Schedule (Europe/Kyiv)   | Purpose                                              |
| -------------------- | ------------------------ | ---------------------------------------------------- |
| `refresh_views`      | hourly at :05            | `REFRESH MATERIALIZED VIEW CONCURRENTLY` × 3         |
| `detect_deals`       | hourly at :10            | Percentile-rule SQL insert into `deals` (ADR-006)   |
| `post_deals`         | every 15 min             | Send unposted deals to Telegram channel              |
| `snapshot_stub`      | 06:00, 18:00             | Placeholder until `apps/ingest` lands (Week 3)       |
| `cleanup_partitions` | 03:00                    | `partman.run_maintenance_proc()` + fallback DROP    |

## Running

Built and orchestrated via the project root `docker-compose.yml`:

```bash
docker compose up scheduler        # tail logs
docker compose run --rm scheduler pytest   # tests
```

## Cross-package dependency

`apps/scheduler/src/jobs/post_deals.py` imports the shared Telegram
publisher from `apps/bot/src/publishers/broadcast.py`. The image
vendors that file at build time — the Dockerfile uses build
context `./apps` so a single `COPY bot/src/publishers/` pulls it in
as `src.publishers` inside the container. The bot service is expected
to import the same file in-tree once its `main.py` is fleshed out.

## Cold-start mode

`detect_deals` reads the Redis key `flag:cold_start`. When set to
`"true"`, the percentile baseline is bypassed and a destination/stars
heuristic runs instead (ADR-006 fallback). Flip the flag via
`redis-cli SET flag:cold_start true` for the first ~30 days, then
`DEL flag:cold_start` once `price_observations` has 60+ days of
history.

## Graceful no-token mode

If `TELEGRAM_BOT_TOKEN` is empty (typical in dev), `post_deals` logs a
skipped event and returns. The rest of the scheduler keeps running.
