# FastTravel

Інформаційний агрегатор турів для українського ринку. **Головне завдання** — знаходити **аномально дешеві дати** на конкретні готелі (коли один день у календарі коштує помітно менше за сусідні) і розсилати їх у Telegram-канал + персональні алерти.

**Не продаємо у себе.** Кнопка "Купити" редіректить на сайт оператора (поки що — [farvater.travel](https://farvater.travel/uk/)).

**Бюджет MVP:** $0/міс (Oracle Cloud Always Free + Cloudflare Workers + R2 free tier). Тверда межа — домен ~$10/рік.

---

## Поточний статус

🟢 **Production-grade local stack** (травень 2026). Усі сервіси проходять lint + tests, Prometheus rules валідні, docker compose валідується для dev/prod/observability профілів. Аудит `docs/AUDIT_REPORT.md` повністю закрито (~130 з 134 знахідок), три високо-ризикові рефактори свідомо відкладено у `docs/superpowers/specs/` з конкретними планами міграції.

🔴 **Що залишилось перед prod deploy** — суто операторські дії (детально у [`docs/OPERATIONS.md`](docs/OPERATIONS.md)):
- ротувати `TELEGRAM_BOT_TOKEN` + `ALERTMANAGER_WEBHOOK_SECRET`
- встановити GitHub Actions secrets (age public key, R2 token, SSH known_hosts)
- створити R2 bucket `fasttravel-tfstate` для terraform remote state
- запустити `terraform apply` на Oracle Cloud → SSH в VM → `git pull` → `docker compose up`

---

## Як виявляються "акційні пропозиції"

Серцевина продукту — `apps/scheduler/src/jobs/detect_deals.py`. Працює раз на годину і зараз запускає одну production-стратегію по таблиці `current_prices`: same-hotel `date_dip`, який створює `calendar_anomaly` тільки коли локальна ціна справді дешевша за порівнянні дати того самого готелю.

| Метод (`detection_method`) | Що порівнюється | Статус |
|---|---|---|
| **`calendar_anomaly` (date_dip)** | ціна одного дня vs trimmed baseline локальних дат **того самого готелю / ночей / meal / room-family-quality-view bucket** | active production detector |
| **`promo_discount`** | реальна strike-through ціна оператора | render/API supported, не активна SQL-гілка detector job |
| **`percentile`** | ціна сьогодні vs історична медіана цього готелю | render/API supported, не активна SQL-гілка detector job |
| **`peer_anomaly`** | ціна vs сусідні готелі | render/API supported для старих/імпортованих рядків; не публікується в каналі |

Канал `post_deals` публікує `calendar_anomaly` від `date_dip` при дисконті ≥ 4%. `peer_anomaly` не йде в канал; персональні алерти пропускають його тільки при дисконті ≥ 25%, інші методи — від ≥ 4%.

Пороги `date_dip` живуть в одному місці: `apps/shared/deal_detection.py` (`DATE_DIP_POLICY`). Поточна політика: check-in через 5-90 днів, сусідні дати ±14 днів, мінімум 4 порівнянні сусідні дати, spread не більше 2.5x, ціна строго нижча за 96% trimmed local baseline і мінімум на 1500 грн дешевша.

Деталі бачить кожен користувач у бот-картці: причина внизу повідомлення (`📉 Аномально дешева дата у цьому готелі`).

---

## Швидкий старт (15 хв)

```bash
# 1. Docker Desktop або OrbStack (рекомендую OrbStack — легший за DD)
brew install --cask orbstack

# 2. Підняти стек
cd ~/Documents/Work/fasttravel
cp .env.example .env
# Відредагуй .env: достатньо GRAFANA_ADMIN_PASSWORD (обов'язково)
# і TELEGRAM_BOT_TOKEN/CHANNEL_ID якщо хочеш реальні пуші

docker compose up -d postgres redis
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up -d

# 3. Прайм materialized views (один раз)
docker compose exec postgres psql -U fasttravel -d fasttravel -c "
  REFRESH MATERIALIZED VIEW current_prices;
  REFRESH MATERIALIZED VIEW hotel_calendar_prices;
  REFRESH MATERIALIZED VIEW price_baselines;"

# 4. Frontend (окремо, не у compose)
cd apps/web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev

# 5. Перевірка
curl http://localhost:8000/health   # → {"status":"ok","db":"ok","redis":"ok"}
```

**URLs:**
- API + Swagger → http://localhost:8000/docs
- Frontend → http://localhost:3000
- Grafana → http://localhost:3001 (admin / `$GRAFANA_ADMIN_PASSWORD`)
- Prometheus → http://localhost:9090

---

## Структура репозиторію

```
fasttravel/
├── apps/
│   ├── api/         FastAPI HTTP сервіс (Python 3.12)
│   ├── bot/         Telegram bot (aiogram 3) + AlertManager webhook
│   ├── scheduler/   APScheduler — snapshot, detect_deals, post_deals, notify
│   ├── ingest/      Бібліотека парсерів / нормалізаторів (імпортується scheduler)
│   ├── shared/      Спільний код:
│   │   ├── infra/       BaseAppSettings, configure_logging, configure_sentry
│   │   └── publishers/  Telegram broadcast helper
│   └── web/         Next.js 15 фронт на Cloudflare Workers (OpenNext)
├── infra/
│   ├── terraform/   Oracle Cloud Always Free IaC + R2 remote state
│   ├── cloud-init.yml  VM bootstrap (Docker + certbot + fail2ban + unattended-upgrades)
│   ├── nginx/       Reverse proxy + LE certs
│   ├── postgres/    Custom Dockerfile (pg_partman + pg_cron + postgis) + WAL archive script
│   ├── prometheus/  rules + alertmanager.yml (9 rules)
│   ├── vector/      Loki log shipper (observability profile)
│   ├── grafana/     Provisioned dashboards
│   └── scripts/     secrets-bootstrap.sh, mypy-ratchet.sh, backup-restore-drill.sh
├── docs/
│   ├── AUDIT_REPORT.md                        Reference: source of all hardening
│   ├── OPERATIONS.md                          Day-2 ops runbook (secrets, restore, mypy)
│   └── superpowers/specs/                     Deferred refactor plans
├── .github/workflows/   CI, deploy-api (workflow_run gated), deploy-web, daily-backup, security-scan, browser-smoke
├── .pre-commit-config.yaml   ruff + prettier + shellcheck + hadolint
├── docker-compose.yml        Local dev (+ observability profile for Loki+Vector)
├── docker-compose.prod.yml   Prod overlay (mem_limits, ports !reset, image-from-GHCR)
└── docker-compose.test.yml   Test overlay (INSTALL_DEV=true variants)
```

---

## Tech stack

| Шар | Технологія | Чому |
|---|---|---|
| Backend | Python 3.12 + FastAPI 0.132 + starlette 0.49 | aiohttp 3.13.5 / starlette CVE-bumped (audit P0 #4-5) |
| Telegram | aiogram **3.25.0** (hard-pinned bot + scheduler) | shared `apps/shared/publishers/broadcast.py` runs у обох → ідентичний API |
| Frontend | Next.js 15 + React **19.2 stable** + Cloudflare Workers | NEW: CSP/HSTS/Permissions-Policy headers, Vitest + RTL |
| DB | Postgres 16 self-hosted (custom image: pg_partman + pg_cron + postgis) | postgis для майбутнього "find hotels near X" |
| Cache | Redis 7 (`maxmemory 512mb`, `allkeys-lru`) | scheduler queue + bot FSM (logical DB /2) |
| Schedule | APScheduler у власному контейнері | post_deals кожні 15 хв, detect_deals щогодини |
| Observability | Prometheus 30d/8GB + AlertManager + Grafana + node/postgres/redis exporters | 9 alert rules; optional Loki+Vector через `--profile observability` |
| Backups | `pg_dump -Fc --compress=9` → age-encrypt → rclone → R2 | parallel restore (`pg_restore -j 4`), ciphertext-only на R2 |

---

## Розробка

### Запуск тестів

```bash
# Bot — використовуй scheduler venv бо там aiogram
cd apps/bot && PYTHONPATH=.:.. ../scheduler/.venv/bin/python -m pytest tests/

# Scheduler local tests + DB integration tests in scheduler-test
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/
docker compose -f docker-compose.yml -f docker-compose.test.yml build api-test scheduler-test
docker compose up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps scheduler-test pytest tests/integration/ -q

# API DB-backed tests: use the compose test image with dev deps
docker compose -f docker-compose.yml -f docker-compose.test.yml build api-test
docker compose up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test pytest -q

# Web (vitest + RTL)
cd apps/web && pnpm test
```

### Lint + typecheck + mypy ratchet

```bash
# Ruff (4 сервіси, всі мають бути clean)
for svc in api scheduler ingest bot; do
  (cd apps/$svc && ../api/.venv/bin/ruff check src tests)
done

# Mypy ratchet — provavily fail CI якщо помилок > baseline
./infra/scripts/mypy-ratchet.sh api scheduler ingest bot

# Web typecheck + lint
cd apps/web && pnpm typecheck && pnpm lint
```

Поточний mypy baseline: `api=0`, `scheduler=0`, `ingest=0`, `bot=70` (legacy aiogram type-narrowing — окремий cleanup PR).

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install     # один раз; далі ruff/prettier/shellcheck/hadolint на кожен коміт
```

---

## Production deploy

Покроковий runbook → [`infra/SETUP.md`](infra/SETUP.md). Чек-лист секретів і ротацій → [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

TL;DR: створити Oracle Cloud Free VM через `terraform apply`, скопіювати `.env` з реальними секретами, `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`. Деплой на main іде через GitHub Actions `deploy-api.yml` (тригериться через `workflow_run` тільки після успішного CI на тому ж SHA — red CI більше не дає green deploy).

---

## Disclaimer

FastTravel — інформаційний агрегатор. Ми не є туроператором або туристичним агентом у розумінні Закону України "Про туризм". Усі тури продають їхні власні постачальники (Join UP, Coral Travel, ALF тощо). Ми лише агрегуємо публічну інформацію про ціни і допомагаємо знайти найкращі пропозиції. Уся відповідальність за виконання договорів — на стороні оператора.
