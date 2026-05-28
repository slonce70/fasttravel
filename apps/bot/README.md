# FastTravel Telegram Bot

aiogram 3 polling bot + aiohttp.web AlertManager webhook receiver, in a
single process. Talks to the FastTravel HTTP API for hotel / deal /
search data and writes subscriber state directly into Postgres.

## Layout

```
apps/bot/
  src/
    main.py                 Boots polling + alert webhook; registers routers
    config.py               Settings — inherits BaseAppSettings from shared/infra
    alert_webhook.py        POST /alerts handler (HMAC-verified, fail-closed in prod)
    handlers/
      commands.py           /start, /help, /channel + reply-keyboard text dispatchers
      deals.py              /deals (paginated), /best (top-10 by discount)
      destinations.py       /destinations
      search_wizard.py      6-step FSM search wizard
      subscribe.py          /subscribe, filter CRUD, alert opt-out
      profile.py            /profile — show subscriber filters
      admin_discovery.py    my_chat_member events (channel pin tracking)
    keyboards/
      main_menu.py          Persistent reply keyboard (BEST/SEARCH/DEALS/…)
      countries.py          Inline country grid
      filters.py            Inline filter pickers (nights/when/budget/meal/stars)
    states/                 FSM state machines for wizard + subscribe
    templates/
      deal.py               MarkdownV2 renderer — method-aware baseline wording + why-line
    infra/
      api_client.py         httpx.AsyncClient over apps/api
      db.py                 asyncpg for subscriber tables
      middleware.py         ThrottleMiddleware + MetricsMiddleware
      metrics.py            Prometheus counters / latency histogram
      logging.py            Thin wrapper over shared.infra.logging
      sentry.py             Thin wrapper over shared.infra.sentry
  tests/                    unit tests; pytest-asyncio
  pyproject.toml            Poetry + ruff config (audit Sprint #8 — was Dockerfile-pinned)
  poetry.lock
  Dockerfile                Multi-stage, USER app, HEALTHCHECK /alerts/health
  pytest.ini                asyncio_mode = auto
```

## Commands

| Command | What it does |
|---|---|
| `/start` | Welcome + reply-keyboard menu |
| `/best` | Top-10 current deals sorted by discount % — single message, 5 inline buttons |
| `/search` | 6-step wizard (country → nights → when → budget → meal → stars) → paginated results |
| `/deals` | Full paginated deals feed (5 per page) |
| `/destinations` | Country catalog with hotel counts |
| `/subscribe` | Manage filter-based personal alerts (sent by scheduler's `notify_subscribers` job) |
| `/profile` | Show current subscriber filters |
| `/channel` | Link to public deals channel |
| `/help` | Help + command list |

## AlertManager webhook

`POST /alerts` (port 9103, internal-only inside the fasttravel docker
network) accepts the Prometheus AlertManager payload and re-broadcasts
each firing/resolved alert to `TELEGRAM_ALERTS_CHAT_ID`. This must be a
private/operator chat, not the public deals group.

Authentication:

- Accepts either `X-Webhook-Secret: <secret>` (custom header, dev path)
  or `Authorization: Bearer <secret>` (AlertManager native).
- Comparison uses `hmac.compare_digest` (constant time).
- **Fail-closed in prod**: an unset `ALERTMANAGER_WEBHOOK_SECRET` in
  `ENVIRONMENT=prod` returns 503 rather than silently accepting (audit
  #2). `Settings.assert_prod_secrets()` also refuses to boot in that
  config.

Health: `GET /alerts/health` → 200 + `{"status":"ok"}`. The bot
container's HEALTHCHECK pings this every 30s.

## Subscriber filter pipeline

```
user → /subscribe → FSM → telegram_subscriber_filters row
                                     ↓
                       scheduler.jobs.notify_subscribers (hourly :15)
                                     ↓
                      SELECT DISTINCT ON (filter_id) deals
                      ORDER BY discount_pct DESC, id DESC
                                     ↓
                      bot.send_message(chat_id=…, parse_mode="MarkdownV2")
                                     ↓
                      telegram_filter_notifications(filter_id, deal_id)
```

`notify_subscribers` requires `discount_pct ≥ 25` for `peer_anomaly`
deals (weaker signal); other detection methods send at `≥ 4%`. Alerts use
the same 6-hour freshness window as public channel posts.
Idempotency is tracked per `(filter_id, deal_id)` so the job can
send the deepest current match first without a scalar cursor hiding other
valid deals.

## Running

```bash
# In Docker (production-like):
docker compose up bot                       # tail logs
docker compose logs -f bot

# Tests (no DB/Redis needed for the unit suite):
cd apps/bot
PYTHONPATH=.:.. ../scheduler/.venv/bin/python -m pytest tests/
```

## Required env vars

| Var | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | prod | Empty in dev → bot idles, alert webhook still runs |
| `TELEGRAM_CHANNEL_ID` | prod | Public deals group/channel for tour posts only |
| `TELEGRAM_ALERTS_CHAT_ID` | prod | Separate private/operator chat for AlertManager notifications |
| `ALERTMANAGER_WEBHOOK_SECRET` | prod | Generate via `openssl rand -hex 32`; mirror into AlertManager config |
| `API_BASE_URL` | always | `http://api:8000` inside compose |
| `DATABASE_URL` | always | bot writes `telegram_subscribers` / `telegram_subscriber_filters` directly |
| `REDIS_URL` | always | logical DB `/2` to avoid colliding with scheduler queue on `/0` |
| `PUBLIC_SITE_URL` | optional | Used to build `/hotels/{slug}` URLs in inline buttons |
| `PUBLIC_CHANNEL_LINK` | optional | `/channel` command CTA |
| `SENTRY_DSN` | optional | Sentry init only when set; includes AsyncioIntegration + SqlalchemyIntegration |

## Architectural decisions worth knowing

- **aiohttp.web (not FastAPI) for the alert webhook.** aiogram already
  depends on aiohttp; adding FastAPI just for `/alerts` would pull in
  Starlette + Pydantic-FastAPI for a single endpoint.
- **Webhook and polling share the same event loop** — same process, same
  graceful-shutdown signal handler. Cleaner than two containers for two
  surfaces that both need the Bot instance.
- **Shared aiogram pin.** Bot's Dockerfile and scheduler's pyproject
  both pin `aiogram==3.25.0` so `apps/shared/publishers/broadcast.py`
  sees identical Bot/MarkdownV2 surface in both processes.
- **MarkdownV2 escaping at the boundary.** Every DB-supplied substring
  (hotel name, destination, operator) flows through `escape_markdown_v2()`
  before reaching the template. Reserved punctuation in template strings
  is pre-escaped.
