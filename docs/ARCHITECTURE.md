# Architecture

## Огляд

FastTravel — інформаційний агрегатор турів. Збирає ціни з туроператорів, нормалізує у єдину БД, показує користувачу через web (Next.js) і Telegram-канал з виявленими "гарячими" знижками.

```
┌─────────────────────────────────────────────────────────────┐
│  CLOUDFLARE (Free)  — DNS, DDoS, CDN, WAF                   │
└─────────────────────────────────────────────────────────────┘
        │                                            │
        ▼                                            ▼
┌──────────────────────┐                ┌──────────────────────────┐
│  Cloudflare Workers  │                │ Oracle Cloud Always Free │
│  (Next.js 15/OpenNext)│ ─── /api/* ─▶│ ARM Ampere A1            │
│                      │                │ 4 vCPU / 24GB / 200GB    │
└──────────────────────┘                │ Reserved Public IP       │
                                        │                          │
                                        │ docker-compose:          │
                                        │  ├─ nginx + LE certs     │
                                        │  ├─ FastAPI (API)        │
                                        │  ├─ aiogram bot          │
                                        │  │   + /alerts webhook   │
                                        │  │   (Sprint 2.3)        │
                                        │  ├─ APScheduler (jobs)   │
                                        │  ├─ Postgres 16          │
                                        │  ├─ Redis 7              │
                                        │  ├─ Prometheus           │
                                        │  ├─ AlertManager         │
                                        │  │   (Sprint 2.3)        │
                                        │  └─ Grafana              │
                                        └──────────────────────────┘
                                                  │
                                                  ▼
                                      ┌──────────────────────┐
                                      │  Data sources        │
                                      │  ├─ ittour API       │
                                      │  ├─ farvater scrape  │
                                      │  │    (bootstrap)    │
                                      │  └─ TBO Holidays     │
                                      │     (hotel content)  │
                                      └──────────────────────┘
```

## Розподіл відповідальностей між сервісами

### `apps/api/` — FastAPI
- HTTP API для фронту (Next.js fetch'ає `/api/hotels/{slug}`, `/api/hotels/{id}/calendar`, `/api/search`, `/api/deals`)
- Read-only від БД (writes тільки через `apps/ingest`)
- Sentry + Prometheus middleware
- CORS дозволений тільки для frontend домена

### `apps/bot/` — Aiogram Telegram bot
- Long-polling режим (без webhook на MVP)
- Команди: `/start`, `/help`, `/website`
- НЕ постить deals сам — це робить `apps/scheduler` worker, який використовує спільну `apps/shared/publishers/broadcast.py` бібліотеку

### `apps/scheduler/` — APScheduler standalone
- Періодичні джоби: snapshot цін, refresh materialized views, deal detection, post deals to Telegram, cleanup partitions
- Окремий процес (не всередині FastAPI) — щоб heavy compute не блокував API requests
- Heart-beat у Redis для self-healing detection

### `apps/ingest/` — Shared data ingestion library
- НЕ запускається як окремий сервіс — імпортується у `apps/scheduler`
- `clients/` — конкретні API/scraper клієнти (ittour, farvater, TBO)
- `normalizers/` — конвертація raw response у унифікований формат
- `pipeline.py` — orchestration (parallel fetch → normalize → dedup → insert)

### `apps/web/` — Next.js 15
- App Router, SSG/SSR/ISR
- `@opennextjs/cloudflare` adapter для деплою на Cloudflare Workers
- API calls ідуть до публічного FastAPI backend на Oracle
- Heatmap календар через react-day-picker з custom DayButton

## Promotions pipeline (Sprint 1A-1F, May 2026)

Operator-flagged promotions live in a separate data path from
algorithmic price-anomaly deals. The May 2026 HAR investigation
(`docs/farvater-har-report.md`) proved that the calendar endpoint
snapshot_farvater uses has ZERO promo flags; the canonical source is
the undocumented `POST /uk/catalog/static-tours` endpoint, which
encodes promo type by URL bucket (`gorjashhie-tury`,
`rannee-bronirovanie`, `akcionnye-tury`) rather than by a column flag.

```
┌────────────────────────────────────────────────────────────────┐
│ static_tours_sweep  (every 2h, FT_STATIC_TOURS_SWEEP_ENABLED)  │
│   for (bucket × country):                                      │
│     POST /uk/catalog/static-tours                              │
│     → FarvaterProdClient (concurrency 3, 1s delay, counter telemetry) │
│     → parse tourPackage.tours[] (15+ fields per row)           │
│     → UPSERT promo_offers (uq key: system_key+bucket+observed) │
└─────────────────────┬──────────────────────────────────────────┘
                      ▼
                ┌──────────────┐
                │ promo_offers │ ── separate from price_observations
                └──────┬───────┘    (own lifecycle: LoadedDate, EndDate)
                      │
       ┌──────────────┴──────────────────────────┐
       ▼                                          ▼
┌──────────────────────┐                ┌───────────────────────────┐
│ detect_deals         │                │ GET /api/promotions       │
│ (FT_DEAL_DETECTION_  │                │   ?bucket=gorjashhie-tury │
│  BUCKETS_ENABLED)    │                │   ?country=TR             │
│   INSERT deals       │                │   ?min_discount_pct=20    │
│   detection_method   │                │ → web /promotions page    │
│   = 'bucket_<slug>'  │                └───────────────────────────┘
└─────────┬────────────┘
          ▼
    ┌──────────┐
    │ deals    │  detection_method in:
    │          │   'percentile'  ← warm/cold price baseline
    └────┬─────┘   'bucket_<slug>' ← promo bucket
         │         'peer_anomaly' ← future ML
         ▼
   post_deals (15 min) → Telegram channel
```

Feature flags:
- `FT_STATIC_TOURS_SWEEP_ENABLED` (default off) — gates the bucket
  ingest sweep
- `FT_DEAL_DETECTION_BUCKETS_ENABLED` (default off) — gates the
  bucket-deal detection branch

Both off by default so a `git pull` + container restart doesn't
silently start filling the Telegram channel with promo-deals before
the operator has verified the new path end-to-end.

## Observability (Sprint 0.5, 2.1-2.3)

Prometheus metrics:
- `fasttravel_job_runs_total{job, outcome}` — counter
- `fasttravel_job_duration_seconds{job}` — histogram
- `fasttravel_last_successful_snapshot_unixtime{job}` — gauge (feeds
  StaleSnapshot alert)
- `fasttravel_prices_written_total{source, country}` — counter
- `fasttravel_promos_ingested_total{bucket, country}` — counter
- `fasttravel_scrape_hotel_failures_total{source, country, reason}` —
  counter (feeds HighScrapeFailureRate when wired up)
- `fasttravel_farvater_breaker_trips_total` — counter
- `fasttravel_refresh_queue_depth` — gauge

Alert rules (`infra/prometheus/rules/fasttravel.yml`):
- `StaleSnapshot` (critical, 14h) — snapshot hasn't completed
- `StaleCatalog` (warning, 36h) — catalog refresh overdue
- `DealsDetectorIdle` (warning, 3h) — detect_deals not running

AlertManager fans firing/resolved alerts to the bot's `/alerts`
webhook (Sprint 2.3), which formats them as MarkdownV2 and posts to
the operator's TELEGRAM_CHANNEL_ID. Optional `X-Webhook-Secret` header
auth via `ALERTMANAGER_WEBHOOK_SECRET` env.

## Data flow

### Refresh price snapshot (2×/день)

1. systemd timer на Oracle спрацьовує о 06:00 і 18:00 UA time
2. `apps/scheduler/src/jobs/snapshot_farvater.py` запускається
3. Для кожного з 300 готелів × 90 днів × 3 тривалості × 2 харчування × 3 оператори:
   - Послати запит до ittour API (або farvater scraper як bootstrap)
   - Concurrency: `asyncio.Semaphore(5)` — не більше 5 одночасних запитів
4. Нормалізувати відповідь через source-specific normalizer у `apps/ingest/src/normalizers/`
5. Dedup: пропустити запис якщо `MD5(price_uah || deep_link)` збігається з минулим observation
6. Bulk insert у `price_observations` (partitioned by week)
7. Записати audit row у `scrape_runs`

### Refresh materialized views (щогодини)

`apps/scheduler/src/jobs/refresh_views.py`:
- `REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices`
- `REFRESH MATERIALIZED VIEW CONCURRENTLY hotel_calendar_prices`
- `REFRESH MATERIALIZED VIEW CONCURRENTLY price_baselines`

### Deal detection (щогодини)

`apps/scheduler/src/jobs/detect_deals.py`:
- SQL trigger з percentile rule (див. план §"Deal Detection")
- Cold-start fallback feature flag у Redis
- INSERT у `deals` таблицю (одна знижка = один рядок)

### Telegram broadcast (кожні 15 хв)

`apps/scheduler/src/jobs/post_deals.py`:
- SELECT deals WHERE posted_at IS NULL LIMIT 5
- Render через template, sendMessage у канал через `apps/shared/publishers/broadcast.py`
- UPDATE posted_at, telegram_msg_id
- Daily cap 30 постів/день per канал

### User browse hotel calendar (real-time)

1. Користувач відкриває `/hotels/[slug]`
2. Next.js на Cloudflare Workers/OpenNext рендерить сторінку, fetch'ає `/api/hotels/{slug}/calendar`
3. FastAPI читає з `hotel_calendar_prices` MV (миттєвий response)
4. React-day-picker рендерить heatmap з color-coded цінами
5. При кліку на дату — client-side fetch `/api/hotels/{id}/offers?date=...&nights=7&meal=AI`
6. FastAPI читає з `current_prices` MV, повертає список offers від різних операторів
7. Користувач клікає "Купити на JoinUp →" — opening нова tab з deep_link

## Storage strategy

### `price_observations` — high-volume, partitioned

- Партиціонування **по тижнях** через `pg_partman`
- 4 партиції наперед, auto-create
- Auto-DROP старше 60 днів
- Очікувані обсяги: ~3-6M рядків/міс (з dedup), ~12M у hot 60-day window = 2.4 GB

### Materialized views (refresh hourly)

- `current_prices` — DISTINCT ON (hotel, config, check_in) latest snapshot
- `hotel_calendar_prices` — MIN(price) GROUP BY (hotel, check_in) для heatmap
- `price_baselines` — p15/p50/p85 percentiles за 60 днів rolling, GROUP BY (hotel, config, month)

### Redis kee patterns

- `hot:hotel:{hotel_id}` — TTL 24h, counter кліків (для hourly snapshot prioritization)
- `dedup:deal:{hotel_id}:{config_hash}` — TTL 24h, anti-spam Telegram
- `rate:scrape:{operator}` — token bucket для rate-limit на джерело
- `cache:calendar:{hotel_id}:{month}` — TTL 12h (preview, основні дані з MV)
- `flag:cold_start` — bool, перемикач алгоритму deal detection

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| ittour API down | scrape_runs.status=failed >3 разів підряд | Fallback на farvater scraper |
| Oracle VM reclaimed (idle) | UptimeRobot alerts | IaC у git → terraform apply → restore from R2 backup |
| Postgres OOM | Grafana alert | Increase shared_buffers, restart |
| Cloudflare 403 на farvater | curl_cffi 403 response | Перейти на ittour direct (якщо токен є) |
| Telegram rate limit | aiogram `RetryAfter` | exponential backoff у broadcast worker |

## Security

- API endpoints — public read, no auth на MVP (немає user accounts)
- Bot token — у `.env`, ніколи не commit
- ittour API key — у `.env`, передається через Docker secrets
- Postgres — слухає тільки на 127.0.0.1, не виставлений назовні
- Redis — те ж саме, тільки локально
- nginx → FastAPI: тільки через Cloudflare, blockаємо direct access до Oracle IP через iptables (тільки 443 і 22)
- SSH — key-only auth, fail2ban активний
- pip/npm dependencies — Dependabot alerts на GitHub

## Scaling path (Tier 2, коли проект довів себе)

- → docker-compose scale (PG залишається 1)
- → +Hetzner CX22 €4/міс як read-replica
- → ClickHouse Cloud free для price_observations
- → Meilisearch для full-text пошуку
- → Sentry Team, Decodo proxy для scraping etc.
