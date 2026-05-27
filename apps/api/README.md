# FastTravel API

FastAPI service exposing read-only HTTP over the price/hotel aggregator.

## Layout

```
apps/api/
  src/
    main.py                 FastAPI app, lifespan, middleware (incl. AmpQueryParamMiddleware)
    config.py               Settings, inherits BaseAppSettings from apps/shared/infra/
    deps.py                 DI providers (get_db, get_redis)
    routers/                HTTP layer
      health.py             /health
      hotels.py             /api/hotels/{slug}, /api/hotels/{id}/{calendar,offers,refresh,hot-ping}
      search.py             /api/search
      deals.py              /api/deals (sort=discount|newest|price)
      promotions.py         /api/promotions  (operator-flagged offers)
      destinations.py       /api/destinations
      seo.py                /robots.txt, /sitemap.xml
    services/               Business logic
      calendar_service.py   heatmap query for hotel calendar
      search_service.py     ranked hotel search with min_price
      deal_service.py       /api/deals listing + sort
      refresh_queue.py      Persistent refresh-queue logic (audit #1.3 split)
      promo_service.py      operator promo lookups
    models/                 SQLAlchemy 2.x async ORM
    schemas/                Pydantic 2 response/request models
    infra/                  Service-local wrappers over apps/shared/infra/
      db.py                 async engine + session factory
      cache.py              Redis client
      logging.py            thin wrapper over shared.infra.logging
      sentry.py             thin wrapper over shared.infra.sentry (adds FastApiIntegration)
      limiter.py            slowapi per-IP keying (CF-Connecting-IP → XFF → client.host)
      middleware.py         AmpQueryParamMiddleware (rewrites ?amp;param=)
  migrations/versions/      Alembic; latest = 018_hotels_coords_postgis.py
  tests/                    pytest + httpx + pytest-asyncio
  alembic.ini
  pyproject.toml
  Dockerfile                multi-stage, USER app, HEALTHCHECK
```

## Running locally

Everything runs in Docker via the repo-root compose file.

```bash
# 1. Copy env template and fill in any secrets you have
cp ../../.env.example ../../.env

# 2. Start backing services
docker compose up -d postgres redis

# 3. Build the API image and apply migrations
docker compose build api
docker compose run --rm api alembic upgrade head

# 4. Prime the materialised views (REFRESH CONCURRENTLY needs a populated MV)
docker compose exec postgres psql -U fasttravel -d fasttravel -c \
  "REFRESH MATERIALIZED VIEW current_prices; \
   REFRESH MATERIALIZED VIEW hotel_calendar_prices; \
   REFRESH MATERIALIZED VIEW price_baselines;"

# 5. Bring up the rest of the backend/runtime stack
docker compose up -d
```

Then:

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Prometheus metrics: <http://localhost:8000/metrics>
- Grafana: <http://localhost:3001> (admin / admin)
- Prometheus: <http://localhost:9090>

The Next.js frontend is not a compose service. Run it from `apps/web`:

```bash
cd ../web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
```

## Migrations

```bash
# Apply
docker compose run --rm api alembic upgrade head

# Autogenerate a new revision from ORM changes
docker compose run --rm api alembic revision --autogenerate -m "your message"

# Downgrade one step
docker compose run --rm api alembic downgrade -1
```

Autogenerate has trouble with:

- Materialised views (treats them as unmanaged objects — review the diff)
- The `price_observations` partitioned parent (declared via raw SQL)
- `pg_partman` calls (must be added by hand)

Write these by hand using `op.execute(...)`.

## Tests

Tests assume `postgres` and `redis` from docker-compose are up.

```bash
docker compose run --rm api pytest -q
```

`tests/conftest.py` wraps every test in a connection-scoped SAVEPOINT and
rolls it back at teardown — there is no leakage between tests and no
need for a separate test database.

## Logging

`src/infra/logging.py` configures structlog:

- `dev` → pretty colour console
- `prod` → JSON lines (one event per stdout line)

Every HTTP request binds an `X-Request-ID` via `CorrelationIdMiddleware`
into `structlog.contextvars`, so every log emitted inside the request
handler automatically carries the id.

## Endpoint contract

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | DB + Redis ping; 200 ok / 503 degraded |
| `GET` | `/api/hotels/{slug}` | Public lookup by SEO slug |
| `GET` | `/api/hotels/{id}/calendar?from=…&to=…&meal=AI&nights=7` | Heatmap; max window 180 days. **Read-only** (audit fix — no Redis mutation). |
| `GET` | `/api/hotels/{id}/offers?date=…&nights=7&meal=AI` | All operator offers for the date |
| `POST` | `/api/hotels/{id}/hot-ping` | Client-driven heat signal (replaces the GET-side INCR). 60/min/IP rate-limited. Returns 204. |
| `POST` | `/api/hotels/{id}/refresh?nights=N` | Enqueue live-price fetch. 10/IP/hour. Dedup via 5-min lock per (hotel, nights). |
| `GET` | `/api/search?country=tr&stars_min=4&…` | Hotel search. Accepts `?amp;param=…` aliases via AmpQueryParamMiddleware. |
| `GET` | `/api/deals?country=tr&sort=discount&limit=50&offset=0` | Recent deals; default `sort=discount` (biggest %). `sort=newest\|price` also supported. Exposes `detection_method` per row. |
| `GET` | `/api/deals/{id}` | Single deal permalink (404 if not found / aged out / synthetic). |
| `GET` | `/api/promotions` | Operator-flagged Farvater promos (bucket-membership; not the same as deals). |
| `GET` | `/api/destinations` | Country list filtered by `has_active_prices`. |

## Production contracts

- `Settings.assert_prod_secrets()` (inherited from `shared.infra.BaseAppSettings`)
  refuses to boot `ENVIRONMENT=prod` with default `_change_me` database
  passwords; the API adds `DATABASE_URL_SYNC` to the offender list.
- Per-IP rate limiter (`src/infra/limiter.py`) reads `CF-Connecting-IP` →
  `X-Forwarded-For[0]` → `request.client.host`. Operator can override the
  trusted-header preference with `RATE_LIMIT_TRUSTED_HEADER` env var.
- AmpQueryParamMiddleware rewrites `?amp;param=…` → `?param=…` before
  route matching. Means every router stays clean; you don't need to
  declare alias Query() params per endpoint (audit #1.3 cleanup).
- Calendar/search/deals endpoints read from real tables and materialized
  views populated by scheduler ingest jobs; no demo seed path is required.
- Affiliate redirects are template-based until partner APIs provide final
  signing rules; unavailable partners stay explicit rather than silently
  pretending checkout happens on FastTravel.

## Architectural decisions worth knowing

- **Poetry over pip-tools.** Stricter lockfile + Docker export story.
- **Postgres 16 Debian (not alpine).** `pg_partman` and `pg_cron` ship as
  PGDG apt packages; alpine would require source builds.
- **`pg_partman` 5.x API.** We call `partman.create_parent(...)`, not the
  old `public.create_parent(...)`.
- **MV refresh priming.** All MVs are created `WITH NO DATA`; first
  refresh **must** be non-CONCURRENT (see step 4 above). Hourly cron
  refreshes thereafter use CONCURRENTLY.
- **Slug vs id endpoints.** Hotel lookup by slug for SEO; calendar/offers
  by numeric id (cheaper). The frontend should cache the id after the
  first lookup.
- **No `alembic upgrade head` on container start.** Migrations are
  always a one-shot. Saves us from surprise schema drift on restarts.
