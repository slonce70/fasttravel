# Infrastructure Inventory

Live-документ. Оновлюємо коли реєструємо новий сервіс або змінюємо креди/IP.

**Last updated:** 2026-05-24 (local release-candidate state)

---

## Поточна стратегія: local release candidate → VPS/Cloudflare Workers cutover

Local Docker runtime, Telegram bot/channel integration, CI build/browser-smoke
wiring, Prometheus targets, and real Farvater-backed data path are already
validated. Production cutover is now gated by external secrets and VPS /
Cloudflare configuration, not by local MVP scaffolding.

## Phase 1: Local development (зараз)

| # | Item | Owner | Status | Note |
|---|---|---|---|---|
| 1 | Local backend/runtime stack | AI/user | ✅ active | `docker compose up -d`; API/bot/scheduler/Prometheus verified; frontend runs from `apps/web` |
| 2 | ittour partner/API access | user | ⏳ pending | External agreement/token; no in-repo placeholder template |
| 3 | TBO Holidays account | user | ⏳ pending | External hotel-content account; configure only after real credentials/docs |
| 4 | Otpusk/TAT backup contact | user | ⏳ pending | External relationship; keep repo free of personal outreach drafts |
| 5 | Telegram bot via @BotFather | user | ✅ active | `@hermes_fine_bot`, token in `.env` as `TELEGRAM_BOT_TOKEN` |
| 6 | Test Telegram channel | user | ✅ active | `@testtyhhh`, id `-1003825850110`, bot can post |
| 7 | (Опційно) GitHub repo `fasttravel` | user | ⏳ pending | Для бекапу + CI/CD |

## Phase 2: Production deploy (коли продукт буде готовий)

| # | Item | Owner | Status | Note |
|---|---|---|---|---|
| 8 | VPS provider (Oracle Free / Hetzner / DigitalOcean) | user | 📅 пізніше | Інфра готова в `infra/`, адаптуємо під обраний провайдер |
| 9 | Static Public IP | user | 📅 пізніше | Для ittour API IP-bind |
| 10 | Domain registration | user | 📅 пізніше | Recommend `.com.ua` (~250 грн/рік) |
| 11 | Cloudflare account | user | 📅 пізніше | Free plan, додати домен |
| 12 | Cloudflare Workers/OpenNext → GitHub repo | user | ✅ repo-ready | `deploy-web.yml` auto-deploys after Cloudflare secrets are added |
| 13 | Cloudflare R2 bucket `fasttravel-backups` | user | 📅 пізніше | 10GB free, 0 egress |
| 14 | Sentry project | AI | 📅 пізніше | Free 5k events/міс |
| 15 | UptimeRobot account | AI | 📅 пізніше | Free 50 monitors |

---

## Active (вже працює)

| Service | Account/ID | Owner | Login URL | Notes |
|---|---|---|---|---|
| Local dev stack | Docker Compose | local | localhost:8000/docs | Postgres+Redis+FastAPI+bot+scheduler+Grafana+Prometheus, валідовано end-to-end |
| Telegram bot | `@hermes_fine_bot` | BotFather | https://t.me/hermes_fine_bot | DM flows + channel broadcast path |
| Telegram channel | `@testtyhhh` | Telegram | https://t.me/testtyhhh | Test/beta broadcast channel |
| Project monorepo | filesystem | local | /Users/trend/Documents/Work/fasttravel | Active local release-candidate worktree |

## Готова інфраструктура у репозиторії

### Локальна розробка (готово, треба запустити)
| Component | Path | Action |
|---|---|---|
| Docker Compose backend/runtime stack | `docker-compose.yml` | `docker compose up -d` |
| Custom Postgres з pg_partman 5.4.3 + pg_cron + pg_trgm | `infra/postgres/` | будується автоматично |
| Alembic migration 001_init | `apps/api/migrations/versions/001_init.py` | 9 таблиць + 8 weekly partitions + 3 MV + всі індекси |
| Prometheus config | `infra/prometheus/prometheus.yml` | scrape API metrics |
| Grafana dashboards | `infra/grafana/dashboards/` | auto-provisioned |

### Production VPS (готово, чекає Phase 2)
| Component | Path | Призначення |
|---|---|---|
| Terraform IaC (Oracle-specific, адаптується) | `infra/terraform/` | один `terraform apply` піднімає VM |
| Cloud-init VM bootstrap | `infra/cloud-init.yml` | docker, certbot, fail2ban, ufw |
| Production docker-compose overlay | `docker-compose.prod.yml` | nginx у front, прод env |
| nginx reverse-proxy з Cloudflare real-IP | `infra/nginx/fasttravel.conf` | rate-limit, HTTPS, security headers |
| systemd timers (snapshot 06/18 + keepalive) | `infra/systemd/` | надійніше за GitHub Actions cron |
| Setup runbook (11 кроків, 0→live ~30 хв) | `infra/SETUP.md` | покрокова інструкція для VPS deploy |
| Production preflight | `infra/scripts/production-preflight.sh` | перевіряє prod compose/env/workflows/Grafana/browser-smoke/live health перед cutover |
| Backup restore drill | `infra/scripts/backup-restore-drill.sh` | відновлює `.sql.gz` dump у чистий Postgres перед R2 upload |
| Web deploy workflow | `.github/workflows/deploy-web.yml` | audit/lint/typecheck/unit/OpenNext/Wrangler dry-run → Cloudflare Workers deploy → optional deployed Playwright smoke |

Production nginx is the container from `docker-compose.prod.yml`; host certbot
uses standalone mode only to create/renew `/etc/letsencrypt` certificates. Host
nginx is intentionally not part of the cutover path, so ports 80/443 have a
single owner after the stack starts.

---

## Credentials inventory

**Усі секрети — у `.env` файлах на сервері або як GitHub Secrets, НЕ commit'ити.**

| Secret name | Where used | How to rotate |
|---|---|---|
| `DATABASE_URL` | apps/api, apps/scheduler, apps/bot | docker-compose `postgres` service password |
| `REDIS_URL` | apps/api, apps/scheduler, apps/bot | docker-compose `redis` config |
| `ITTOUR_API_TOKEN` | apps/ingest/clients/ittour.py | partner portal ittour (TBD коли отримаємо) |
| `TBO_USERNAME` + `TBO_PASSWORD` | apps/ingest/clients/tbo_holidays.py | TBO partner portal |
| `TELEGRAM_BOT_TOKEN` | apps/bot, apps/scheduler (broadcast) | @BotFather → `/revoke` → новий |
| `TELEGRAM_CHANNEL_ID` | apps/scheduler/jobs/post_deals.py | Telegram channel admin |
| `SENTRY_DSN` | apps/api, apps/bot, apps/scheduler | Sentry project settings |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | GitHub Actions backup workflow | Cloudflare R2 dashboard |
| `OCI_SSH_PRIVATE_KEY` | GitHub Actions deploy workflow | new ssh-keygen → update VM authorized_keys |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | GitHub Actions web deploy workflow | Cloudflare dashboard → Account API tokens |
| `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_TELEGRAM_CHANNEL_URL` | Build-time public frontend config in web deploy workflow | GitHub repository variables |
| `PREVIEW_NEXT_PUBLIC_API_URL`, `PREVIEW_NEXT_PUBLIC_TELEGRAM_CHANNEL_URL` | Optional preview build-time public frontend config | GitHub repository variables |
| `FRONTEND_PRODUCTION_URL`, `FRONTEND_PREVIEW_URL` | Optional deployed browser smoke in web deploy workflow | GitHub repository variables or secrets |

Backend deploy to VPS does not require a long-lived GHCR PAT. The workflow uses
the built-in `GITHUB_TOKEN` twice: first on the GitHub runner to push images,
then inside the SSH deploy step to log the VPS into `ghcr.io` immediately before
`docker compose pull`.

## Production preflight gate

Перед ручним VPS cutover або перед розбором red deploy запускаємо:

```bash
./infra/scripts/secrets-bootstrap.sh .env.prod
# заповнити реальні TELEGRAM_*, GHCR image tags, R2/Sentry/provider secrets
ENV_FILE=.env.prod STRICT_ENV=1 ./infra/scripts/production-preflight.sh
./infra/scripts/backup-restore-drill.sh
```

У CI цей самий скрипт запускається без strict prod env, щоб перевірити
compose overlay, workflow YAML, Grafana JSON, stale production strings і live
health checks там, де локальний стек уже піднятий.

Daily backup workflow також запускає `backup-restore-drill.sh` для щойно
отриманого VPS dump перед upload у R2. Якщо restore падає, backup не
позначається придатним.

Після Cloudflare Workers/VPS cutover запусти GitHub Actions workflow
**Browser Smoke** з `base_url=https://fasttravel.com.ua`. Він проганяє той
самий Playwright smoke по Telegram CTA, search → hotel detail і deals → buy
links уже проти живого frontend URL.

Web deploy автоматизований у **Deploy Web**: без Cloudflare secrets workflow
gracefully skip'иться; з `CLOUDFLARE_ACCOUNT_ID` і `CLOUDFLARE_API_TOKEN`
кожен `main` push у `apps/web/**` проходить frontend quality gates,
OpenNext build, Wrangler dry-run і deploy у Worker `fasttravel-web`. Якщо
задати `FRONTEND_PRODUCTION_URL` / `FRONTEND_PREVIEW_URL`, той самий workflow
проганяє Playwright smoke проти deployed URL після публікації. Public
`NEXT_PUBLIC_*` значення також передаються на build-time, щоб браузерний
bundle не зашив локальний fallback.

---

## Reserved IPs

| IP | Region | Service | Whitelist target |
|---|---|---|---|
| TBD | eu-frankfurt-1 | Oracle VM (primary) | ittour API IP-bind |

---

## Domain & DNS

| Domain | Registrar | Cloudflare zone | Target | Status |
|---|---|---|---|---|
| `fasttravel.com.ua` | TBD | TBD | Cloudflare Worker `fasttravel-web` | ⏳ |
| `api.fasttravel.com.ua` | TBD | TBD | Oracle Reserved IP / VPS nginx container | ⏳ |

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
