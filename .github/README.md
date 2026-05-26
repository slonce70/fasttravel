# `.github/` — CI/CD, automation, repo meta

Цей каталог тримає всю автоматизацію навколо репо: GitHub Actions workflows,
Dependabot, шаблони issue/PR, CODEOWNERS.

> **Local-first phase.** На даний момент backend/runtime stack
> (`docker compose up -d`) локально працює без жодних GitHub секретів.
> Frontend запускається окремо з `apps/web` або через Playwright smoke.
> Workflows які потребують VPS / R2 (deploy, backup) мають **graceful skip** — вони запускаються за розкладом,
> але no-op'ять, поки відповідні secrets відсутні.

---

## Workflows

| File | Trigger | Що робить | Потребує secrets |
|---|---|---|---|
| `ci.yml` | PR + push до `main` | Lint, type check, тести (API + scheduler + ingest + bot + web), build фронту, OpenNext build, local API + Playwright browser smoke, docker compose smoke build | _(none)_ optionally `CODECOV_TOKEN` |
| `deploy-api.yml` | Push до `main` (зміни в `apps/*` / `infra/*` / compose) + manual | Build і push образів до GHCR, SSH у VPS, GHCR login, alembic migration, recreate backend сервісів, health check | VPS SSH + (опц.) webhook |
| `deploy-web.yml` | Push до `main` (зміни в `apps/web`) + manual | Audit/lint/typecheck/unit, OpenNext build, Wrangler dry-run, deploy Cloudflare Worker, optional deployed Playwright smoke | Cloudflare Workers |
| `browser-smoke.yml` | Manual | Playwright smoke проти deployed frontend URL після cutover/deploy | _(none)_ |
| `daily-backup.yml` | Cron `0 1 * * *` (01:00 UTC) + manual | SSH у VPS, `pg_dump → gzip → R2`, retain 30 last | VPS SSH + R2 |
| `security-scan.yml` | Cron `0 4 * * 1` (Monday 04:00 UTC) + manual | Trivy на всі Docker images (SARIF у Security tab), `pip-audit` на api/scheduler, `pnpm audit` на web | _(none)_ |

### Concurrency / cost

| Workflow | Тривалість (orientative) | Запусків / міс | Хвилин / міс |
|---|---|---|---|
| CI | ~5–7 хв | ~20 PR | ~120 |
| CI browser smoke | ~5 хв | ~20 PR | ~100 |
| Daily backup | ~2 хв | 30 | ~60 |
| Security scan | ~10 хв | 4 | ~40 |
| Deploy API | ~6 хв | ~10 deploy | ~60 |
| Deploy Web | ~5 хв | ~10 deploy | ~50 |
| Browser Smoke | ~2 хв | ~10 deploy | ~20 |
| **Разом** | | | **~450 хв** |

Free tier для private repo — 2000 хв/міс. Комфортно влазимо з 5x запасом.

---

## Як додавати secrets

`Settings → Secrets and variables → Actions → New repository secret`.

### Required to graduate з local-first → продакшен

#### Backup (`daily-backup.yml`)
| Secret | Опис | Приклад |
|---|---|---|
| `BACKUP_SSH_HOST` | IP / hostname VPS | `1.2.3.4` |
| `BACKUP_SSH_USER` | SSH user з доступом до docker | `fasttravel` |
| `BACKUP_SSH_KEY` | Private SSH key (OpenSSH PEM) | `-----BEGIN OPENSSH PRIVATE KEY----- ...` |
| `BACKUP_SSH_KNOWN_HOSTS` | _(опц.)_ Вивід `ssh-keyscan <host>` | `1.2.3.4 ssh-ed25519 AAAA...` |
| `R2_ACCOUNT_ID` | Cloudflare account ID | `abc123...` |
| `R2_ACCESS_KEY_ID` | R2 API token (Access Key ID) | `...` |
| `R2_SECRET_ACCESS_KEY` | R2 API token (Secret Access Key) | `...` |
| `R2_BUCKET` | Bucket для бекапів | `fasttravel-backups` |

#### Deploy (`deploy-api.yml`)
| Secret | Опис |
|---|---|
| `DEPLOY_SSH_HOST` | VPS host |
| `DEPLOY_SSH_USER` | SSH user |
| `DEPLOY_SSH_KEY` | Private SSH key |
| `DEPLOY_SSH_KNOWN_HOSTS` | _(опц.)_ keyscan output |
| `DEPLOY_NOTIFY_WEBHOOK` | _(опц.)_ Slack/Discord webhook на failure |

> **GHCR auth** використовує built-in `GITHUB_TOKEN` (нічого додавати не треба).
> Runner логіниться для push, а VPS логіниться перед `docker compose pull` тим
> самим workflow-scoped token. Залежить від `permissions: { packages: write }`
> у workflow і від GHCR packages, linked to this repo.
> `deploy-api.yml` no-op'ить, якщо відсутній будь-який із required VPS secrets:
> `DEPLOY_SSH_HOST`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KEY`.

#### Web deploy (`deploy-web.yml`)
| Secret | Опис |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID, де живе Worker `fasttravel-web` |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token з правом `Edit Cloudflare Workers`, scoped на потрібний account/zone |
| `NEXT_PUBLIC_API_URL` | _(опц.)_ Production API URL для build-time Next.js env; default `https://api.fasttravel.com.ua` |
| `NEXT_PUBLIC_TELEGRAM_CHANNEL_URL` | _(опц.)_ Production channel CTA URL; default `https://t.me/testtyhhh` |
| `PREVIEW_NEXT_PUBLIC_API_URL` | _(опц.)_ Preview API URL; default `https://staging-api.fasttravel.com.ua` |
| `PREVIEW_NEXT_PUBLIC_TELEGRAM_CHANNEL_URL` | _(опц.)_ Preview channel CTA URL; default бере production channel URL |
| `FRONTEND_PRODUCTION_URL` | _(опц.)_ Repository variable або secret для автоматичного Playwright smoke після production deploy |
| `FRONTEND_PREVIEW_URL` | _(опц.)_ Repository variable або secret для автоматичного Playwright smoke після preview deploy |

`daily-backup.yml` no-op'ить, якщо відсутній будь-який required VPS/R2 secret;
це захищає scheduled runs від червоних падінь у local-first фазі.

Workflow no-op'ить без Cloudflare secrets. Коли вони є, deploy проходить через
`pnpm audit`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm cf:build`,
Wrangler dry-run і тільки потім публікує Worker. Якщо `FRONTEND_PRODUCTION_URL`
або `FRONTEND_PREVIEW_URL` заданий, той самий job проганяє Playwright smoke
проти вже розгорнутого URL і завантажує артефакти на failure.

Production frontend and backend are intentionally split by host:
`fasttravel.com.ua` is the Cloudflare Worker, while `api.fasttravel.com.ua` is
the VPS nginx container. Keep `NEXT_PUBLIC_API_URL` on the API host, not on the
frontend host.

#### CI (`ci.yml`)
| Secret | Опис |
|---|---|
| `CODECOV_TOKEN` | _(опц.)_ Codecov upload token. Без нього CI пройде, просто без coverage |

---

## Перед першим push на GitHub

1. У `Settings → Branches → main`:
   - Enable "Require a pull request before merging".
   - Enable "Require status checks to pass" → додати `backend (api) lint + test`, `scheduler lint + test`, `ingest lint + test`, `bot lint + test`, `frontend lint + build`, `browser smoke (local API)`, `docker compose validate + build`.
   - Enable "Require review from Code Owners".
2. У `Settings → Actions → General`:
   - Workflow permissions: `Read and write` (потрібно для GHCR push з deploy-api).
3. Поки немає VPS — deploy/backup workflows будуть no-op'ити з логом
   `Skipping: ... secrets not configured`. Це очікувано.

---

## Lockfiles

Lockfiles закомічені для API, scheduler, ingest і web:

- `apps/api/poetry.lock`
- `apps/scheduler/poetry.lock`
- `apps/ingest/poetry.lock`
- `apps/web/pnpm-lock.yaml`

CI використовує lockfile-friendly installs і не має генерувати нові lockfiles
під час звичайного прогону.

---

## Issue / PR шаблони

- `PULL_REQUEST_TEMPLATE.md` — основний шаблон PR (що/чому/як перевірено/checklist).
- `ISSUE_TEMPLATE/bug_report.md` — баг репорти.
- `ISSUE_TEMPLATE/feature_request.md` — фічі.

GitHub автоматично підхопить їх при `New issue` / `New PR`.
