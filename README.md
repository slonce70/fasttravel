# FastTravel

Інформаційний агрегатор турів для українського ринку з календарем цін по днях для кожного готелю і Telegram-ботом який постить гарячі знижки.

**Не продаємо у себе.** Кнопка "Купити" редіректить на сайт оператора.

**Reference competitors:** [farvater.travel](https://farvater.travel/uk/), [turne.ua](https://turne.ua/ua/tour/turciya)

**Бюджет MVP:** $0/міс (free-tier інфра). Тверда межа — домен ~$10/рік.

---

## Поточний статус

🚧 **Local release candidate.** Локальний Docker runtime, Telegram bot/channel,
реальні Farvater-backed ціни, веб-флоу, Prometheus/Grafana і CI/deploy wiring
перевірені локально. Повний production cutover ще потребує VPS/Cloudflare
secrets, rotated prod `.env`, backup/restore drill і фінальний deploy smoke.

**Актуальний production plan:** [`docs/superpowers/plans/2026-05-24-production-readiness.md`](docs/superpowers/plans/2026-05-24-production-readiness.md)

### Sprint 1-3 highlights (May 2026)

- **Promotions pipeline:** `GET /api/promotions` + web `/promotions`
  page, backed by `promo_offers` table and
  `static_tours_sweep` job. See
  [`docs/farvater-har-report.md`](docs/farvater-har-report.md) for
  why this is a separate channel from /api/deals.
- **AlertManager + Telegram bridge:** Prometheus alerts post to
  TELEGRAM_CHANNEL_ID via the bot's `/alerts` webhook (Sprint 2.3).
- **Production-tier HTTP client** for farvater with circuit breaker
  (5×429/15min → 1h cooldown) and adaptive throttle. The Redis daily
  request counter is telemetry only unless a positive cap is explicitly passed.
- **Schema canary** (daily 05:00 Kyiv) validates the static-tours +
  calendar JSON shapes so a silent upstream rename surfaces as an
  alert rather than a slow trickle of rejected rows.
- **Job reorder** (Sprint 1F): decay 04:00 → baselines 04:15 →
  cleanup 04:30 → sitemap fallback 04:45 → canary 05:00.
- Feature flags ship OFF: `FT_STATIC_TOURS_SWEEP_ENABLED` and
  `FT_DEAL_DETECTION_BUCKETS_ENABLED` — flip on after verifying the
  first run by hand (see `.env.example`).

---

## Що тобі (користувачу) треба зробити зараз

### ✅ #1. Запустити стек локально *(15 хв)*

```bash
# Install Docker Desktop або OrbStack (рекомендую OrbStack — легший)
brew install --cask orbstack

# Підняти backend/runtime stack (API, bot, scheduler, DB, Redis, monitoring)
cd ~/Documents/Work/fasttravel
cp .env.example .env
docker compose up -d postgres redis
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up -d

# Frontend запускається окремо
cd apps/web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev

# Перевірка
curl http://localhost:8000/health
# → {"status":"ok","db":"ok","redis":"ok"}
```

**Доступні URL:**
- API → http://localhost:8000/docs (Swagger UI)
- Frontend dev → http://localhost:3000 (`cd apps/web && pnpm dev`)
- Browser smoke server → http://127.0.0.1:3100 під час `pnpm test:e2e`
- Grafana → http://localhost:3001 (admin/admin)
- Prometheus → http://localhost:9090

Якщо backend/runtime не запускається — дивись `docker compose logs`. Якщо
frontend не стартує — дивись лог команди `pnpm dev` у `apps/web`.

### ✅ #2. (Опційно) підключити GitHub remote *(10 хв)*

Репозиторій вже має локальну git-історію. Для CI/CD треба створити GitHub repo
і додати remote:

```bash
cd ~/Documents/Work/fasttravel
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

---

## Production deploy (коли захочеш зняти повноцінний VPS)

**Це Phase 2** — поки не блокує локальну розробку.

Коли будеш готовий зняти VPS (Hetzner CX22 €4/міс, або будь-який інший Ubuntu 22.04+):

1. Прочитай [`infra/SETUP.md`](infra/SETUP.md) — там покроковий runbook для Oracle Cloud Always Free (можна адаптувати на будь-який VPS)
2. Залежно від провайдера:
   - **Oracle Cloud Free** — використовуй `infra/terraform/` як IaC ($0/міс назавжди, ARM 4 vCPU/24GB)
   - **Hetzner / DigitalOcean / Linode** — переписати Terraform під відповідний провайдер (просто), АБО створити VM руками і запустити `infra/cloud-init.yml` через User Data
3. Налаштувати домен + Cloudflare (DNS + CDN + WAF, безкоштовно)
4. Згенерувати `.env.prod`, заповнити реальні секрети, прогнати preflight,
   скопіювати `.env` на VPS і виконати
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

Інфра-як-код (Terraform + cloud-init + nginx + systemd timers) лежить в
[`infra/`](infra/). Перед деплоєм запускай:

```bash
./infra/scripts/secrets-bootstrap.sh .env.prod
# заповни TELEGRAM_*, API_IMAGE/BOT_IMAGE/SCHEDULER_IMAGE, R2/Sentry/etc.
ENV_FILE=.env.prod STRICT_ENV=1 ./infra/scripts/production-preflight.sh

# доказ, що pg_dump не тільки створюється, а й відновлюється
./infra/scripts/backup-restore-drill.sh
```

---

## Структура репозиторію

```
fasttravel/
├── apps/
│   ├── api/         # FastAPI backend (Python 3.12)
│   ├── bot/         # Telegram bot (aiogram 3)
│   ├── scheduler/   # APScheduler standalone (price refresh, deal detection)
│   ├── ingest/      # Shared data ingestion library (ittour, farvater, TBO clients)
│   └── web/         # Next.js 15 frontend (Cloudflare Workers/OpenNext)
├── infra/
│   ├── terraform/   # Oracle Cloud IaC
│   ├── cloud-init.yml # VM bootstrap script
│   ├── nginx/       # Reverse proxy + LE certs
│   ├── systemd/     # Service unit files
│   └── grafana/     # Monitoring dashboards
├── docs/
│   ├── ARCHITECTURE.md   # System architecture overview
│   ├── DECISIONS.md      # ADR log
│   └── INFRASTRUCTURE.md # Inventory of infra, release gates, external accounts
├── .github/workflows/    # CI + deploy + backup + browser smoke
├── docker-compose.yml    # Local dev stack
└── docker-compose.prod.yml # Production overlay
```

---

## Tech Stack (короткий огляд)

| Шар | Технологія | Чому |
|---|---|---|
| Backend | Python 3.12 + FastAPI 0.115 | Найкраща екосистема для scraping + AI-агенти добре пишуть Python |
| Frontend | Next.js 15 + Cloudflare Workers/OpenNext | НЕ Vercel — Hobby забороняє commercial |
| DB | Postgres 16 self-hosted | НЕ Supabase — 500MB замало, наші 2.4GB hot |
| Cache | Redis 7 self-hosted | Не Upstash — 500k ops/добу замало |
| Telegram | aiogram 3 | Найзріліша Python-бібліотека |
| Schedule | APScheduler + systemd timers | GitHub Actions cron ненадійний для 15-хв |
| Hosting | Oracle Cloud Always Free | 4 vCPU ARM + 24GB безкоштовно назавжди |
| Frontend host | Cloudflare Workers | CDN/WAF інтеграція + OpenNext runtime |
| Storage | Cloudflare R2 | 10GB free, 0 egress |

Деталі і обґрунтування — у [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Roadmap (8 тижнів MVP)

- **Done locally** — Docker stack, Postgres schema, FastAPI, scheduler,
  Telegram bot/channel, real Farvater-backed prices, web MVP, CI gates,
  Prometheus/Grafana wiring.
- **Next production gates** — rotated prod secrets, VPS/Cloudflare secrets,
  backup/restore verification, final deploy smoke.

---

## Local development

```bash
# (один раз) install Docker Desktop або Orbstack для Mac
brew install --cask orbstack  # рекомендую, легший за Docker Desktop

# 1. створити .env з прикладу
cp .env.example .env
# відредагуй секрети (DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID)

# 2. підняти БД і Redis
docker compose up -d postgres redis

# 3. збудувати API image
docker compose build api

# 4. виконати міграції (one-shot, см. ADR-014)
docker compose run --rm api alembic upgrade head

# 5. приміряти materialized views (вперше)
docker compose exec postgres psql -U fasttravel -d fasttravel -c \
  "REFRESH MATERIALIZED VIEW current_prices; \
   REFRESH MATERIALIZED VIEW hotel_calendar_prices; \
   REFRESH MATERIALIZED VIEW price_baselines;"

# 6. запустити backend/runtime stack
docker compose up -d

# API → http://localhost:8000/docs (Swagger UI)
# Metrics → http://localhost:8000/metrics
# Grafana → http://localhost:3001 (admin/admin)
# Prometheus → http://localhost:9090
```

Frontend dev:
```bash
cd apps/web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
# → http://localhost:3000
```

Перевірка:
```bash
curl http://localhost:8000/health
# → {"status":"ok","db":"ok","redis":"ok"}

# production-surface sanity checks; live checks виконуються якщо стек запущений
./infra/scripts/production-preflight.sh

# browser smoke against local web + live local API
cd apps/web
pnpm test:e2e:install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm test:e2e
```

Детальна архітектура — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Інженерні рішення з обґрунтуванням — [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Disclaimer

FastTravel — інформаційний агрегатор. Ми не є туроператором або туристичним агентом у розумінні Закону України "Про туризм". Усі тури продають їх власні постачальники (Join UP, Coral Travel, ALF тощо). Ми лише агрегуємо публічну інформацію про ціни і допомагаємо знайти найкращі пропозиції. Уся відповідальність за виконання договорів — на стороні оператора.
