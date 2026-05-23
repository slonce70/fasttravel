# FastTravel

Інформаційний агрегатор турів для українського ринку з календарем цін по днях для кожного готелю і Telegram-ботом який постить гарячі знижки.

**Не продаємо у себе.** Кнопка "Купити" редіректить на сайт оператора.

**Reference competitors:** [farvater.travel](https://farvater.travel/uk/), [turne.ua](https://turne.ua/ua/tour/turciya)

**Бюджет MVP:** $0/міс (free-tier інфра). Тверда межа — домен ~$10/рік.

---

## Поточний статус

🚧 **Day 1 — Local development.** Проект ініціалізовано, базова структура та інфра-як-код створені. **Розробляємо і тестуємо локально**, продакшен VPS — пізніше.

**Затверджений план:** `~/.claude/plans/moonlit-humming-fountain.md`

---

## Що тобі (користувачу) треба зробити зараз

### ✅ #1. Запустити стек локально *(15 хв)*

```bash
# Install Docker Desktop або OrbStack (рекомендую OrbStack — легший)
brew install --cask orbstack

# Підняти весь стек
cd ~/Documents/Work/fasttravel
cp .env.example .env
docker compose up -d postgres redis
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up -d

# Перевірка
curl http://localhost:8000/health
# → {"status":"ok","db":"ok","redis":"ok"}
```

**Доступні URL:**
- API → http://localhost:8000/docs (Swagger UI)
- Frontend → http://localhost:3000 *(після того як Frontend агент завершить)*
- Grafana → http://localhost:3001 (admin/admin)
- Prometheus → http://localhost:9090

Якщо щось не запускається — дай мені вивід `docker compose logs`.

### ✅ #2. Відправити 3 partner emails *(30 хв, найважливіше!)*

Це **найдовший lead-time** у проекті (відповіді 1-4 тижні). Відправ навіть якщо інше не готово.

Шаблони в [docs/outreach/](docs/outreach/) — копіюєш у свій email, замінюєш `{{YOUR_NAME}}`, `{{YOUR_EMAIL}}`, `{{YOUR_PHONE}}`, відправляєш.

**Адресати:**
1. `contacts@ittour.com.ua` — IT-tour API (основний канал даних)
2. `partners@tboholidays.com` — TBO Holidays (готельний контент)
3. Telegram: `@Vira_Otpusk` — Otpusk/TAT.ua (backup)

**Коли відправиш:** скажи "emails надіслані".

### ✅ #3. (Опційно) Git init + GitHub repo *(10 хв)*

Якщо хочеш бекап і CI:

```bash
cd ~/Documents/Work/fasttravel
git init
git add .
git commit -m "initial bootstrap"
# Потім створи repo на github.com/new, додай remote, push
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
4. Скопіювати `docker-compose.prod.yml` на VPS, налаштувати `.env`, `docker compose up -d`

Інфра-як-код (Terraform + cloud-init + nginx + systemd timers) уже **готова і протестована** — лежить в [`infra/`](infra/).

---

## Структура репозиторію

```
fasttravel/
├── apps/
│   ├── api/         # FastAPI backend (Python 3.12)
│   ├── bot/         # Telegram bot (aiogram 3)
│   ├── scheduler/   # APScheduler standalone (price refresh, deal detection)
│   ├── ingest/      # Shared data ingestion library (ittour, farvater, TBO clients)
│   └── web/         # Next.js 15 frontend (Cloudflare Pages)
├── infra/
│   ├── terraform/   # Oracle Cloud IaC
│   ├── cloud-init.yml # VM bootstrap script
│   ├── nginx/       # Reverse proxy + LE certs
│   ├── systemd/     # Service unit files
│   └── grafana/     # Monitoring dashboards
├── docs/
│   ├── ARCHITECTURE.md   # System architecture overview
│   ├── DECISIONS.md      # ADR log
│   ├── INFRASTRUCTURE.md # Inventory of infra (IPs, accounts, contacts)
│   └── outreach/         # Partner email templates
├── .github/workflows/    # CI + daily backups + sitemap
├── docker-compose.yml    # Local dev stack
└── docker-compose.prod.yml # Production overlay
```

---

## Tech Stack (короткий огляд)

| Шар | Технологія | Чому |
|---|---|---|
| Backend | Python 3.12 + FastAPI 0.115 | Найкраща екосистема для scraping + AI-агенти добре пишуть Python |
| Frontend | Next.js 15 + Cloudflare Pages | НЕ Vercel — Hobby забороняє commercial |
| DB | Postgres 16 self-hosted | НЕ Supabase — 500MB замало, наші 2.4GB hot |
| Cache | Redis 7 self-hosted | Не Upstash — 500k ops/добу замало |
| Telegram | aiogram 3 | Найзріліша Python-бібліотека |
| Schedule | APScheduler + systemd timers | GitHub Actions cron ненадійний для 15-хв |
| Hosting | Oracle Cloud Always Free | 4 vCPU ARM + 24GB безкоштовно назавжди |
| Frontend host | Cloudflare Pages | Unlimited bandwidth, 500 builds/міс |
| Storage | Cloudflare R2 | 10GB free, 0 egress |

Деталі і обґрунтування — у [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Roadmap (8 тижнів MVP)

- **Week 1** — Bootstrap (Oracle setup, домен, emails, repo, infra IaC) ← **зараз тут**
- **Week 2** — Core infra (docker-compose, Postgres schema, FastAPI/bot skeletons)
- **Week 3** — Data sourcing (ittour client АБО farvater scraper, TBO content, 300 готелів seed)
- **Week 4-5** — Frontend MVP (Next.js, hotel page з price calendar heatmap)
- **Week 6** — Deal detection + Telegram broadcast
- **Week 7-8** — CI/CD, observability, beta launch

---

## Local development

```bash
# (один раз) install Docker Desktop або Orbstack для Mac
brew install --cask orbstack  # рекомендую, легший за Docker Desktop

# 1. створити .env з прикладу
cp .env.example .env
# відредагуй секрети (DATABASE_URL, REDIS_URL, TG_BOT_TOKEN — поки можеш залишити заглушки)

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

# 6. запустити весь стек
docker compose up -d

# API → http://localhost:8000/docs (Swagger UI)
# Metrics → http://localhost:8000/metrics
# Grafana → http://localhost:3001 (admin/admin)
# Prometheus → http://localhost:9090
```

Перевірка:
```bash
curl http://localhost:8000/health
# → {"status":"ok","db":"ok","redis":"ok"}
```

Детальна архітектура — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Інженерні рішення з обґрунтуванням — [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Disclaimer

FastTravel — інформаційний агрегатор. Ми не є туроператором або туристичним агентом у розумінні Закону України "Про туризм". Усі тури продають їх власні постачальники (Join UP, Coral Travel, ALF тощо). Ми лише агрегуємо публічну інформацію про ціни і допомагаємо знайти найкращі пропозиції. Уся відповідальність за виконання договорів — на стороні оператора.
