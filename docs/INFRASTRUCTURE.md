# Infrastructure Inventory

Live-документ. Оновлюємо коли реєструємо новий сервіс або змінюємо креди/IP.

**Last updated:** 2026-05-23 (ініціалізовано)

---

## Поточна стратегія: local-first, VPS пізніше

**Day 1-2 пріоритети** — локальна розробка через docker-compose. Production VPS зніметься коли продукт буде готовий до beta-launch (Week 6-8).

## Phase 1: Local development (зараз)

| # | Item | Owner | Status | Note |
|---|---|---|---|---|
| 1 | Local Docker stack | user | ⏳ pending | `docker compose up -d` після Docker Desktop/OrbStack install |
| 2 | Email до contacts@ittour.com.ua | user | ⏳ pending | Шаблон у `docs/outreach/01-ittour.md` (без IP — додамо при підключенні) |
| 3 | Email до partners@tboholidays.com | user | ⏳ pending | Шаблон у `docs/outreach/02-tbo-holidays.md` |
| 4 | Telegram → @Vira_Otpusk | user | ⏳ pending | Шаблон у `docs/outreach/03-otpusk-tat.md` |
| 5 | Telegram bot via @BotFather (для local testing) | user | ⏳ pending | Token у `.env` як `TG_BOT_TOKEN` |
| 6 | Test Telegram channel (приватний, для тестів) | user | ⏳ pending | Bot як admin |
| 7 | (Опційно) GitHub repo `fasttravel` | user | ⏳ pending | Для бекапу + CI/CD |

## Phase 2: Production deploy (коли продукт буде готовий)

| # | Item | Owner | Status | Note |
|---|---|---|---|---|
| 8 | VPS provider (Oracle Free / Hetzner / DigitalOcean) | user | 📅 пізніше | Інфра готова в `infra/`, адаптуємо під обраний провайдер |
| 9 | Static Public IP | user | 📅 пізніше | Для ittour API IP-bind |
| 10 | Domain registration | user | 📅 пізніше | Recommend `.com.ua` (~250 грн/рік) |
| 11 | Cloudflare account | user | 📅 пізніше | Free plan, додати домен |
| 12 | Cloudflare Pages → GitHub repo | user | 📅 пізніше | Auto-deploy фронту |
| 13 | Cloudflare R2 bucket `fasttravel-backups` | user | 📅 пізніше | 10GB free, 0 egress |
| 14 | Sentry project | AI | 📅 пізніше | Free 5k events/міс |
| 15 | UptimeRobot account | AI | 📅 пізніше | Free 50 monitors |

---

## Active (вже працює)

| Service | Account/ID | Owner | Login URL | Notes |
|---|---|---|---|---|
| Local dev stack | Docker Compose | local | localhost:8000/docs | Postgres+Redis+FastAPI+Grafana+Prometheus, валідовано end-to-end |
| Project monorepo | filesystem | local | ~/Documents/Work/fasttravel | 83 файли, готово до `git init` |

## Готова інфраструктура у репозиторії

### Локальна розробка (готово, треба запустити)
| Component | Path | Action |
|---|---|---|
| Docker Compose dev stack | `docker-compose.yml` | `docker compose up -d` |
| Custom Postgres з pg_partman 5.4.3 + pg_cron + pg_trgm | `infra/postgres/` | будується автоматично |
| Alembic migration 001_init | `apps/api/migrations/versions/001_init.py` | 9 таблиць + 8 weekly partitions + 3 MV + всі індекси |
| Prometheus config | `infra/prometheus/prometheus.yml` | scrape API metrics |
| Grafana dashboards | `infra/grafana/dashboards/` | auto-provisioned |

### Production VPS (готово, чекає Phase 2)
| Component | Path | Призначення |
|---|---|---|
| Terraform IaC (Oracle-specific, адаптується) | `infra/terraform/` | один `terraform apply` піднімає VM |
| Cloud-init VM bootstrap | `infra/cloud-init.yml` | docker, nginx, certbot, fail2ban, ufw |
| Production docker-compose overlay | `docker-compose.prod.yml` | nginx у front, прод env |
| nginx reverse-proxy з Cloudflare real-IP | `infra/nginx/fasttravel.conf` | rate-limit, HTTPS, security headers |
| systemd timers (snapshot 06/18 + keepalive) | `infra/systemd/` | надійніше за GitHub Actions cron |
| Setup runbook (11 кроків, 0→live ~30 хв) | `infra/SETUP.md` | покрокова інструкція для VPS deploy |

---

## Credentials inventory

**Усі секрети — у `.env` файлах на сервері або як GitHub Secrets, НЕ commit'ити.**

| Secret name | Where used | How to rotate |
|---|---|---|
| `DATABASE_URL` | apps/api, apps/scheduler, apps/bot | docker-compose `postgres` service password |
| `REDIS_URL` | apps/api, apps/scheduler, apps/bot | docker-compose `redis` config |
| `ITTOUR_API_TOKEN` | apps/ingest/clients/ittour.py | partner portal ittour (TBD коли отримаємо) |
| `TBO_API_USER` + `TBO_API_PASSWORD` | apps/ingest/clients/tbo_holidays.py | TBO partner portal |
| `TG_BOT_TOKEN` | apps/bot, apps/scheduler (broadcast) | @BotFather → `/revoke` → новий |
| `TG_CHANNEL_ID` | apps/scheduler/jobs/post_deals.py | Telegram channel admin |
| `SENTRY_DSN_API`, `SENTRY_DSN_BOT` | apps/api, apps/bot | Sentry project settings |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | GitHub Actions backup workflow | Cloudflare R2 dashboard |
| `OCI_SSH_PRIVATE_KEY` | GitHub Actions deploy workflow | new ssh-keygen → update VM authorized_keys |

---

## Reserved IPs

| IP | Region | Service | Whitelist target |
|---|---|---|---|
| TBD | eu-frankfurt-1 | Oracle VM (primary) | ittour API IP-bind |

---

## Domain & DNS

| Domain | Registrar | Cloudflare zone | A record → | Status |
|---|---|---|---|---|
| TBD | TBD | TBD | Oracle Reserved IP | ⏳ |

---

## Contacts

| Person/Service | Email/TG | Context |
|---|---|---|
| IT-tour (Kyiv) | contacts@ittour.com.ua | API партнерство (Track A) |
| TBO Holidays | partners@tboholidays.com | Free hotel content account (Track Г) |
| Otpusk/TAT.ua | @Vira_Otpusk (Telegram) | Backup-постачальник цін (Track Б) |

---

## Cost ledger

| Month | Service | Charge | Notes |
|---|---|---|---|
| 2026-05 | — | $0 | Bootstrap, тільки free-tier |

Targeting **$0/міс fixed + ~$10/рік domain** = $0.84/міс амортизовано.
