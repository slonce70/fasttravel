# FastTravel Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current FastTravel local MVP into a production-ready release candidate with honest Telegram/channel links, reproducible deploy images, working observability, green quality gates, and a concrete VPS/Cloudflare deployment path.

**Architecture:** Keep the product as an aggregator, not a checkout flow. Stabilize the existing FastAPI + APScheduler + aiogram + Next.js stack by fixing runtime drift first, then CI/deploy wiring, then production secrets/backup/monitoring gates. Use real data only; unavailable partner integrations remain disabled or explicitly gated.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, APScheduler, aiogram 3, Postgres 16, Redis 7, Next.js 15, pnpm, Docker Compose, nginx, Prometheus, Grafana, GitHub Actions, GHCR, Cloudflare Workers/OpenNext, Cloudflare R2.

**Execution status on 2026-05-24:** Local release-candidate hardening completed through phases 0-8. Verified: Telegram Bot API returns `@hermes_fine_bot`, channel API returns `@testtyhhh`, local DB has posted deals with Telegram message ids, frontend/channel/bot links point to `https://t.me/testtyhhh`, bot discovery handler is wired, Docker prod image variables render exact GHCR tags, bot security scan context matches the real Dockerfile context, Poetry locks are current for API/scheduler/ingest, prod secret guards exist for API/bot/scheduler, Farvater HTTP client follows redirects, generic ingest inserts resolve `operator_id` and use the price observation conflict guard, the fake `snapshot_stub` scheduler heartbeat has been removed, `snapshot_hot` has regression tests for SCAN/top-N/refresh-lock behavior, stale audit documentation has been deleted, Next.js is patched to `15.5.18`, PostCSS is pinned through `pnpm.overrides` to a non-vulnerable version, deprecated `@cloudflare/next-on-pages` has been replaced with `@opennextjs/cloudflare`, deal permalinks now use `GET /api/deals/{id}` with enriched hotel context and the same real-source filter as the public deal feed, hotel auto-refresh is throttled so browser smoke does not trip the API rate limit, frontend country selectors dedupe country ISO rows defensively, CI now runs frontend unit tests, production dependency audit, OpenNext build, and local API-backed Playwright browser smoke with an ephemeral `ci-e2e` fixture, `deploy-web.yml` is ready to deploy Cloudflare Workers after Cloudflare secrets are added and can run deployed Playwright smoke when a frontend URL variable is configured, Playwright smoke covers Telegram/search/hotel/deals/deal-permalink, local compose runtime is healthy, Prometheus reports API/bot/scheduler/prometheus as `up`, and restore drill passes against the local compose database. Remaining work is external production cutover: real VPS/Cloudflare deploy, strict prod env validation, and deployed browser smoke against the public URL.

**Additional hardening on 2026-05-24 evening:** `CODEOWNERS` now points to the real GitHub owner instead of `@YOUR_USERNAME`; `.github/README.md` no longer documents a missing `nightly-sitemap.yml` placeholder; `production-preflight.sh` now fails on placeholder CODEOWNERS and README workflow references that do not exist. The `ci-e2e` browser-smoke seed is now opt-in only (`FASTTRAVEL_ALLOW_E2E_SEED=1` and non-prod env), has a cleanup mode, and accidental local `ci-e2e-*` rows were removed from the live dev DB so local public API smoke uses real Farvater-derived data. The preflight now also checks a reachable compose database for `ci-e2e` fixture rows and fails the release gate if any are present. `docker-compose.yml` explicitly passes the opt-in env into the API container, and preflight verifies that contract so the CI browser-smoke seed cannot silently lose its opt-in at the compose boundary.

**Documentation cleanup:** Removed stale `docs/outreach/*` partner-email templates with personal placeholders and pre-launch wording. Current docs now state partner integrations as external pending work and keep the production repo focused on verified runtime/deploy facts.

**Docs drift cleanup:** README/web docs now distinguish normal Next dev (`localhost:3000`) from Playwright smoke (`127.0.0.1:3100`), remove stale frontend-agent/bootstrap wording, and reflect that the calendar meal-plan filter is implemented. Architecture/deploy docs now reference the real shared publisher path (`apps/shared/publishers`) and the live sitemap route.

**Operator flow cleanup:** Root/API/GitHub/infra docs now describe `docker compose up -d` as the backend/runtime stack, not the full product including the Next.js frontend. Frontend local dev is documented as a separate `apps/web` command, matching the actual compose service list.

**Production deploy/runbook cleanup:** `deploy-api.yml` now logs the VPS into GHCR before `docker compose pull`, `daily-backup.yml` now checks the full VPS/R2 secret contract before leaving local-first no-op mode, and production systemd/cloud-init/runbook paths now use `docker-compose.yml + docker-compose.prod.yml` together. The systemd snapshot timer now runs the real `src.jobs.snapshot_farvater` module, and cloud-init healthcheck verifies `/health` from inside the API container instead of probing a host port that prod intentionally does not publish.

**Nginx/HTTPS cutover cleanup:** Production now has a single 80/443 owner: the nginx container from `docker-compose.prod.yml`. Host certbot uses standalone mode only to provision/renew `/etc/letsencrypt`, Grafana basic-auth is mounted into the container, unsupported Brotli directives were removed from the official `nginx:1.27-alpine` config, and `nginx -t` was verified against that image with fake certs and the same mounts.

**Public host contract cleanup:** Production frontend and backend are now documented and guarded as separate hosts: `fasttravel.com.ua` belongs to the Cloudflare Worker, while `api.fasttravel.com.ua` belongs to the VPS nginx container. The nginx config serves the API host, provisions certificates under `/etc/letsencrypt/live/api.fasttravel.com.ua/`, and proxies FastAPI `/health` without the `/api` prefix so cutover checks hit a real route.

---

## File Map

- `docs/superpowers/plans/2026-05-24-production-readiness.md`: this execution plan and status tracker.
- `apps/bot/src/handlers/admin_discovery.py`: keep the Telegram chat-id discovery handler added during channel setup.
- `apps/bot/src/main.py`: keep discovery router registration and verify it is committed.
- `apps/web/src/app/telegram/page.tsx`: replace the legacy hardcoded Telegram channel URL with env-backed public channel config.
- `apps/web/src/lib/site-config.ts`: centralize public frontend links that are safe to expose to the browser.
- `apps/web/.env.example`, `apps/web/wrangler.jsonc`, `apps/web/README.md`: document and configure `NEXT_PUBLIC_TELEGRAM_CHANNEL_URL`.
- `apps/web/e2e/smoke.spec.ts`, `apps/web/playwright.config.ts`: repeatable browser smoke for Telegram, search → hotel detail, and deals.
- `.github/workflows/browser-smoke.yml`: manual post-cutover browser smoke against a deployed frontend URL.
- `.github/workflows/deploy-web.yml`: gated Cloudflare Workers deploy with frontend quality gates and Wrangler dry-run.
- `docker-compose.prod.yml`: make prod service images configurable through env vars so the deploy workflow can pull GHCR tags.
- `.github/workflows/deploy-api.yml`: build bot with the correct `./apps` context and pass exact image tags to production compose.
- `.github/workflows/security-scan.yml`: scan bot with the same build context as production.
- `.github/workflows/ci.yml`: use committed lockfiles and keep lint/test/build commands aligned with local verification.
- `infra/prometheus/prometheus.yml`: verify bot and scheduler scrape jobs are loaded in live Prometheus.
- `infra/grafana/dashboards/fasttravel-app.json`: align dashboard queries with emitted metric names.
- `infra/scripts/secrets-bootstrap.sh`: keep as the prod `.env` generator; verify variables match app configs.
- `infra/scripts/production-preflight.sh`: local/CI-safe production-surface gate before VPS cutover.
- `infra/scripts/backup-restore-drill.sh`: prove PostgreSQL dumps restore before treating backups as usable.
- `apps/api/src/config.py`, `apps/bot/src/config.py`, `apps/scheduler/src/config.py`: enforce production-secret sanity consistently.
- `apps/api/scripts/seed_e2e.py`: keep ephemeral browser-smoke fixtures gated behind explicit opt-in and cleanup-safe.
- `apps/scheduler/src/jobs/sitemap_long_tail.py` and Farvater ingest helpers: normalize or follow 301 URLs to reduce noisy failed fetches.
- `apps/scheduler/src/jobs/snapshot_hot.py`: keep hot-priority refresh using SCAN and per-hotel refresh-lock checks.
- `apps/api/migrations/versions/007_price_obs_natural_unique.py`: existing natural uniqueness guard for real observations.
- `apps/ingest/src/pipeline.py`: resolve `operator_code` to `operators.id` and use the same conflict guard as scheduler writers.

---

## Phase 0: Baseline And Worktree Hygiene

### Task 0.1: Confirm Dirty Tree Ownership

**Files:**
- Inspect: `apps/bot/src/main.py`
- Inspect: `apps/bot/src/handlers/admin_discovery.py`
- Delete if accidental: `apps/api/uv.lock`
- Delete if accidental: `apps/ingest/uv.lock`
- Delete if accidental: `apps/scheduler/uv.lock`

- [ ] **Step 1: Capture status**

Run:
```bash
git status --short --branch
git diff -- apps/bot/src/main.py
git diff --check
```
Expected: only intentional source/docs/workflow changes remain; no whitespace errors.

- [ ] **Step 2: Remove accidental uv locks if the repo still uses Poetry locks**

Run:
```bash
git ls-files apps/api/uv.lock apps/ingest/uv.lock apps/scheduler/uv.lock
rm -f apps/api/uv.lock apps/ingest/uv.lock apps/scheduler/uv.lock
```
Expected: `git ls-files` prints nothing for those paths; generated uv lockfiles disappear from `git status`.

- [ ] **Step 3: Verify admin discovery is intentionally present**

Run:
```bash
python - <<'PY'
from pathlib import Path
main = Path("apps/bot/src/main.py").read_text()
handler = Path("apps/bot/src/handlers/admin_discovery.py").read_text()
assert "admin_discovery" in main
assert "@router.my_chat_member()" in handler
print("admin discovery wired")
PY
```
Expected: `admin discovery wired`.

## Phase 1: Telegram And Frontend Truth

### Task 1.1: Make The Public Telegram Link Configurable

**Files:**
- Create: `apps/web/src/lib/site-config.ts`
- Modify: `apps/web/src/app/telegram/page.tsx`
- Modify: `apps/web/.env.example`
- Modify: `apps/web/wrangler.jsonc`
- Modify: `apps/web/README.md`

- [ ] **Step 1: Reproduce stale link**

Run:
```bash
rg -n "NEXT_PUBLIC_TELEGRAM_CHANNEL_URL|t.me/" apps/web
```
Expected before fix: `apps/web/src/app/telegram/page.tsx` contains a hardcoded legacy channel URL; env variable is absent.

- [ ] **Step 2: Add public site config**

Create `apps/web/src/lib/site-config.ts`:
```ts
export const TELEGRAM_CHANNEL_URL =
  process.env.NEXT_PUBLIC_TELEGRAM_CHANNEL_URL ?? 'https://t.me/testtyhhh';
```

- [ ] **Step 3: Use config in Telegram page**

In `apps/web/src/app/telegram/page.tsx`, replace the hardcoded `TG_CHANNEL` constant with:
```ts
import { TELEGRAM_CHANNEL_URL } from '@/lib/site-config';

const TG_CHANNEL = TELEGRAM_CHANNEL_URL;
```

- [ ] **Step 4: Document env**

Add to `apps/web/.env.example`:
```env
NEXT_PUBLIC_TELEGRAM_CHANNEL_URL=https://t.me/testtyhhh
```

Add to `apps/web/wrangler.jsonc` production and preview vars:
```toml
NEXT_PUBLIC_TELEGRAM_CHANNEL_URL = "https://t.me/testtyhhh"
```

- [ ] **Step 5: Verify**

Run:
```bash
cd apps/web
pnpm typecheck
pnpm build
```
Expected: both exit 0. Browser check `/telegram` and verify CTA href is `https://t.me/testtyhhh`.

### Task 1.2: Verify Bot And Channel Runtime

**Files:**
- No source changes unless verification fails.

- [ ] **Step 1: Verify Telegram API identity**

Run with local `.env` loaded:
```bash
set -a; source .env; set +a
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | jq '{ok, id:.result.id, username:.result.username}'
curl -fsS --get "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getChat" \
  --data-urlencode "chat_id=${TELEGRAM_CHANNEL_ID}" | jq '{ok, id:.result.id, title:.result.title, username:.result.username}'
```
Expected: bot username `hermes_fine_bot`; channel username `testtyhhh`.

- [ ] **Step 2: Verify DB broadcast tracking**

Run:
```bash
docker compose exec -T postgres psql -U fasttravel -d fasttravel -c \
"SELECT COUNT(*) AS posted, MIN(telegram_msg_id), MAX(telegram_msg_id) FROM deals WHERE posted_at IS NOT NULL;"
```
Expected: posted count is non-zero and message ids are populated.

## Phase 2: Runtime Drift And Observability

### Task 2.1: Rebuild Scheduler And Bot Images From Current Source

**Files:**
- No source changes unless build fails.

- [ ] **Step 1: Confirm no long ingest is active**

Run:
```bash
docker compose logs --no-color --tail=120 scheduler | rg "sitemap.done|sitemap.country.progress|post_deals|started"
```
Expected: latest long-tail startup run has a `sitemap.done` line or there is no active progress stream.

- [ ] **Step 2: Rebuild and recreate app containers**

Run:
```bash
docker compose build api bot scheduler
docker compose up -d api bot scheduler prometheus
```
Expected: containers recreate without errors.

- [ ] **Step 3: Verify metrics endpoints from inside containers**

Run:
```bash
docker compose exec -T bot python - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:9102/metrics", timeout=3).status)
PY
docker compose exec -T scheduler python - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:9101/metrics", timeout=3).status)
PY
```
Expected: both print `200`.

### Task 2.2: Reload Prometheus Targets

**Files:**
- Verify: `infra/prometheus/prometheus.yml`

- [ ] **Step 1: Restart Prometheus after mounted config changes**

Run:
```bash
docker compose up -d prometheus
curl -fsS 'http://localhost:9090/api/v1/targets' \
  | jq '.data.activeTargets[] | {job:.labels.job, health, scrapeUrl, lastError}'
```
Expected: jobs include `fasttravel-api`, `fasttravel-bot`, `fasttravel-scheduler`, and `prometheus`; all are `up`.

### Task 2.3: Align Grafana Dashboard With Real Metrics

**Files:**
- Modify: `infra/grafana/dashboards/fasttravel-app.json`

- [ ] **Step 1: List emitted metric names**

Run:
```bash
curl -fsS http://localhost:8000/metrics | rg '^# HELP|^fasttravel_' | head -n 80
docker compose exec -T scheduler python - <<'PY'
import urllib.request
text = urllib.request.urlopen("http://127.0.0.1:9101/metrics", timeout=3).read().decode()
print("\n".join(line for line in text.splitlines() if line.startswith("# HELP fasttravel_") or line.startswith("fasttravel_")))
PY
```
Expected: scheduler metrics use `fasttravel_job_runs_total`, `fasttravel_job_duration_seconds`, and `fasttravel_refresh_queue_depth`.

- [ ] **Step 2: Replace stale dashboard queries**

Use these PromQL expressions:
```promql
histogram_quantile(0.95, sum(rate(fasttravel_job_duration_seconds_bucket{job="snapshot_farvater"}[6h])) by (le))
sum(increase(fasttravel_job_runs_total{job="detect_deals",outcome="success"}[1h]))
fasttravel_refresh_queue_depth
histogram_quantile(0.95, sum(rate(fasttravel_job_duration_seconds_bucket[6h])) by (le, job))
```

- [ ] **Step 3: Verify dashboard JSON**

Run:
```bash
jq empty infra/grafana/dashboards/fasttravel-app.json
rg -n "legacy snapshot/deals/Postgres-stat metric names" infra/grafana/dashboards/fasttravel-app.json
```
Expected: `jq` exits 0; `rg` finds no stale metric names.

## Phase 3: Production Deploy Wiring

### Task 3.1: Make Prod Compose Pull Exact GHCR Images

**Files:**
- Modify: `docker-compose.prod.yml`
- Modify: `.github/workflows/deploy-api.yml`

- [ ] **Step 1: Reproduce deploy mismatch**

Run:
```bash
rg -n "image:|context: ./apps/bot|docker compose .*pull" docker-compose.prod.yml .github/workflows/deploy-api.yml
```
Expected before fix: prod compose comments out GHCR images; deploy builds GHCR images but compose still refers to local dev image names.

- [ ] **Step 2: Add configurable prod images**

In `docker-compose.prod.yml`:
```yaml
  api:
    image: ${API_IMAGE:-fasttravel/api:dev}

  bot:
    image: ${BOT_IMAGE:-fasttravel/bot:dev}

  scheduler:
    image: ${SCHEDULER_IMAGE:-fasttravel/scheduler:dev}
```

- [ ] **Step 3: Fix bot build context in deploy workflow**

In `.github/workflows/deploy-api.yml`, use:
```yaml
      - name: Build and push bot
        uses: docker/build-push-action@v6
        with:
          context: ./apps
          file: ./apps/bot/Dockerfile
```

- [ ] **Step 4: Pass exact images on VPS**

Before `docker compose pull` in the remote SSH script, export:
```bash
export API_IMAGE="${{ steps.tags.outputs.prefix }}-api:${{ steps.tags.outputs.sha }}"
export BOT_IMAGE="${{ steps.tags.outputs.prefix }}-bot:${{ steps.tags.outputs.sha }}"
export SCHEDULER_IMAGE="${{ steps.tags.outputs.prefix }}-scheduler:${{ steps.tags.outputs.sha }}"
```
Use those exports for `pull`, `run --rm api alembic upgrade head`, and `up -d`.

- [ ] **Step 5: Verify compose renders**

Run:
```bash
API_IMAGE=ghcr.io/example/fasttravel-api:sha \
BOT_IMAGE=ghcr.io/example/fasttravel-bot:sha \
SCHEDULER_IMAGE=ghcr.io/example/fasttravel-scheduler:sha \
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/tmp/fasttravel-prod.yml
rg -n "ghcr.io/example" /tmp/fasttravel-prod.yml
```
Expected: rendered config contains all three GHCR image refs.

### Task 3.2: Fix Security Scan Bot Build Context

**Files:**
- Modify: `.github/workflows/security-scan.yml`

- [ ] **Step 1: Patch matrix**

Change the bot image matrix entry to:
```yaml
          - name: bot
            context: ./apps
            file: ./apps/bot/Dockerfile
            tag: fasttravel/bot:scan
```

- [ ] **Step 2: Verify workflow syntax shape**

Run:
```bash
python - <<'PY'
from pathlib import Path
text = Path(".github/workflows/security-scan.yml").read_text()
assert "name: bot" in text
assert "context: ./apps\n            file: ./apps/bot/Dockerfile" in text
print("security scan bot context ok")
PY
```
Expected: `security scan bot context ok`.

### Task 3.3: Use Committed Frontend Lockfile In CI

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Verify lock exists**

Run:
```bash
test -f apps/web/pnpm-lock.yaml
```
Expected: exit 0.

- [ ] **Step 2: Switch install to frozen lockfile**

In `frontend-lint-build`, set:
```yaml
      - name: Install dependencies
        run: pnpm install --frozen-lockfile
```

- [ ] **Step 3: Verify local install**

Run:
```bash
cd apps/web
pnpm install --frozen-lockfile
```
Expected: exits 0.

## Phase 4: Quality Gates

### Task 4.1: Make Ruff Gates Green Or Explicitly Scoped

**Files:**
- Modify only files reported by `ruff check` / `ruff format --check`.

- [ ] **Step 1: Reproduce**

Run:
```bash
uv run --with ruff==0.7.4 ruff check apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
uv run --with ruff==0.7.4 ruff format --check apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
```
Expected before fix: any reported files are either fixed or deliberately excluded in project-specific CI.

- [ ] **Step 2: Apply safe formatting**

Run:
```bash
uv run --with ruff==0.7.4 ruff check --fix apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
uv run --with ruff==0.7.4 ruff format apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
```

- [ ] **Step 3: Re-run and inspect diff**

Run:
```bash
uv run --with ruff==0.7.4 ruff check apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
uv run --with ruff==0.7.4 ruff format --check apps/api/src apps/api/tests apps/scheduler/src apps/scheduler/tests apps/ingest/src apps/ingest/tests apps/bot/src apps/bot/tests
git diff --stat
```
Expected: ruff exits 0; diff contains only formatting/import cleanup or reviewed safe edits.

### Task 4.2: Full Local Test Matrix

**Files:**
- No source changes unless a test reveals a real bug.

- [ ] **Step 1: API tests inside compose network**

Run:
```bash
docker compose run --rm --user root \
  -v "$PWD/apps/api/src:/app/src:ro" \
  -v "$PWD/apps/api/tests:/app/tests:ro" \
  api sh -lc 'pip install --no-cache-dir pytest pytest-asyncio slowapi >/tmp/pip-test-install.log && pytest tests'
```
Expected: `12 passed`.

- [ ] **Step 2: Scheduler tests**

Run:
```bash
PYTHONPATH=apps/scheduler:apps uv run \
  --with apscheduler==3.10.4 --with 'sqlalchemy[asyncio]==2.0.36' --with asyncpg==0.30.0 \
  --with redis==5.2.0 --with aiogram==3.13.1 --with 'httpx[http2]==0.27.2' \
  --with pydantic==2.9.2 --with pydantic-settings==2.6.0 --with structlog==24.4.0 \
  --with sentry-sdk==2.18.0 --with tzdata==2024.2 --with prometheus-client==0.21.0 \
  --with pytest --with pytest-asyncio pytest apps/scheduler/tests
```
Expected: `9 passed`.

- [ ] **Step 3: Ingest tests**

Run:
```bash
PYTHONPATH=apps/ingest uv run \
  --with 'httpx[http2]==0.27.2' --with curl-cffi==0.7.4 --with selectolax==0.3.27 \
  --with tenacity==9.0.0 --with 'sqlalchemy[asyncio]==2.0.36' --with asyncpg==0.30.0 \
  --with redis==5.2.0 --with pydantic==2.9.2 --with pydantic-settings==2.6.0 \
  --with structlog==24.4.0 --with pytest --with pytest-asyncio --with pytest-vcr \
  --with vcrpy==6.0.2 --with respx==0.21.1 --with fakeredis==2.26.1 pytest apps/ingest/tests
```
Expected: `24 passed`.

- [ ] **Step 4: Bot tests**

Run:
```bash
PYTHONPATH=apps/bot:apps uv run \
  --with aiogram==3.13.1 --with structlog==24.4.0 --with pydantic-settings==2.6.0 \
  --with pydantic==2.9.2 --with httpx==0.27.2 --with redis==5.2.0 \
  --with prometheus-client==0.21.0 --with sentry-sdk==2.18.0 \
  --with 'sqlalchemy[asyncio]==2.0.36' --with asyncpg==0.30.0 \
  --with pytest --with pytest-asyncio pytest apps/bot/tests
```
Expected: `16 passed`.

- [ ] **Step 5: Web checks**

Run:
```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```
Expected: all exit 0.

## Phase 5: Production Secrets And Safety

### Task 5.1: Add Prod Secret Guards To Bot And Scheduler

**Files:**
- Modify: `apps/bot/src/config.py`
- Modify: `apps/bot/src/main.py`
- Modify: `apps/scheduler/src/config.py`
- Modify: `apps/scheduler/src/main.py`
- Test: `apps/bot/tests/test_config.py`
- Test: `apps/scheduler/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add tests that instantiate settings with `environment="prod"` and default dev DB/Grafana markers, then assert the new guard raises `RuntimeError`.

- [ ] **Step 2: Implement guard**

Add `assert_prod_secrets()` to bot and scheduler settings. At minimum, fail prod when `DATABASE_URL` contains `_change_me` or `fasttravel_dev`; for scheduler also fail when Telegram token/channel are missing if `deals_daily_cap > 0`.

- [ ] **Step 3: Call guard at startup**

Call `settings.assert_prod_secrets()` near the start of `main()` in both services.

- [ ] **Step 4: Verify service tests**

Run bot and scheduler test commands from Task 4.2.

### Task 5.2: Confirm Backup, Restore, And Secret Rotation Runbook

**Files:**
- Modify if stale: `infra/SETUP.md`
- Modify if stale: `.github/workflows/daily-backup.yml`
- Modify if stale: `infra/scripts/secrets-bootstrap.sh`

- [ ] **Step 1: Verify bootstrap output variables**

Run:
```bash
tmpdir="$(mktemp -d)"
outfile="$tmpdir/.env.prod"
infra/scripts/secrets-bootstrap.sh "$outfile"
rg -n "POSTGRES_PASSWORD|DATABASE_URL|DATABASE_URL_SYNC|GRAFANA_ADMIN_PASSWORD|TELEGRAM_BOT_TOKEN|TELEGRAM_CHANNEL_ID" "$outfile"
rm -rf "$tmpdir"
```
Expected: all required variables exist; generated passwords are not default values.

- [ ] **Step 2: Render backup workflow**

Run:
```bash
python - <<'PY'
from pathlib import Path
text = Path(".github/workflows/daily-backup.yml").read_text()
for key in ["BACKUP_SSH_HOST", "R2_ACCOUNT_ID", "R2_BUCKET", "pg_dump"]:
    assert key in text
print("backup workflow has required gates")
PY
```
Expected: `backup workflow has required gates`.

## Phase 6: Data Quality And Ingest Hardening

### Task 6.1: Fix Farvater 301 Noise

**Files:**
- Modify: `apps/scheduler/src/jobs/sitemap_long_tail.py` or the shared Farvater fetch helper used by that job.
- Test: `apps/scheduler/tests/test_sitemap_long_tail.py`

- [ ] **Step 1: Write failing test**

Create a test that feeds a URL ending with a trailing slash or known redirect pattern into the fetch helper and asserts the client follows redirects or canonicalizes before logging a warning.

- [ ] **Step 2: Implement canonical follow**

Set the HTTP client request to follow redirects for safe Farvater hotel page GETs:
```python
await client.get(url, follow_redirects=True)
```
or normalize stored sitemap URLs to the canonical final URL when the upstream returns `301`.

- [ ] **Step 3: Verify**

Run scheduler tests and inspect a fresh small sitemap run log. Expected: 301 warnings are materially reduced; 404/no inventory warnings remain visible.

### Task 6.2: Add Natural Uniqueness To `price_observations`

**Files:**
- Create: `apps/api/migrations/versions/011_price_observations_natural_unique.py`
- Modify writers that insert price observations if they need `ON CONFLICT DO NOTHING`.
- Test: migration smoke in API test DB.

- [ ] **Step 1: Inspect duplicates**

Run:
```bash
docker compose exec -T postgres psql -U fasttravel -d fasttravel -c "
SELECT hotel_id, operator_id, check_in, nights, meal_plan, observed_at, COUNT(*)
FROM price_observations
GROUP BY 1,2,3,4,5,6
HAVING COUNT(*) > 1
LIMIT 20;"
```
Expected: know whether cleanup is needed before adding the constraint.

- [ ] **Step 2: Add migration**

Create a concurrent-safe unique index over:
```sql
(hotel_id, operator_id, check_in, nights, meal_plan, observed_at)
```
For partitioned tables, apply the index to the parent only if Postgres accepts it for existing partition layout; otherwise create partition index logic matching current partman layout.

- [ ] **Step 3: Verify migrations**

Run:
```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic downgrade -1
docker compose run --rm api alembic upgrade head
```
Expected: upgrade/downgrade/upgrade completes without data loss.

## Phase 7: Production Cutover Checklist

### Task 7.0: Cloudflare Workers Web Deploy Gate

**Files:**
- Verify: `.github/workflows/deploy-web.yml`
- Verify: `apps/web/wrangler.jsonc`
- Verify: `.github/README.md`

- [ ] **Step 1: Configure GitHub Actions secrets**

Required secrets:
```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
FRONTEND_PRODUCTION_URL (optional but recommended for automatic deployed smoke)
FRONTEND_PREVIEW_URL (optional)
NEXT_PUBLIC_API_URL (optional, default https://api.fasttravel.com.ua)
NEXT_PUBLIC_TELEGRAM_CHANNEL_URL (optional, default https://t.me/testtyhhh)
PREVIEW_NEXT_PUBLIC_API_URL (optional)
PREVIEW_NEXT_PUBLIC_TELEGRAM_CHANNEL_URL (optional)
```
Expected: token is scoped to the production account/zone with `Edit Cloudflare Workers` permission.

- [ ] **Step 2: Verify deploy workflow locally before first push**

Run:
```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/deploy-web.yml"); puts "deploy-web yaml ok"'
cd apps/web
pnpm audit --prod --audit-level moderate
pnpm lint
pnpm typecheck
pnpm test
pnpm cf:build
pnpm exec wrangler deploy --env="" --dry-run --outdir .open-next-dry-run
```
Expected: all commands exit 0; dry-run prints Worker upload size without publishing.

### Task 7.1: VPS/Cloudflare Release Candidate Gate

**Files:**
- Modify if stale: `infra/SETUP.md`
- Modify if stale: `docs/INFRASTRUCTURE.md`

- [ ] **Step 1: Confirm DNS and secrets**

Required external state:
```text
DEPLOY_SSH_HOST
DEPLOY_SSH_USER
DEPLOY_SSH_KEY
DEPLOY_SSH_KNOWN_HOSTS
BACKUP_SSH_HOST
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
Cloudflare Workers production env:
  NEXT_PUBLIC_API_URL=https://api.fasttravel.com.ua
  NEXT_PUBLIC_TELEGRAM_CHANNEL_URL=https://t.me/testtyhhh
```
Expected: all production secrets live in GitHub/Cloudflare/VPS secret stores, never in git.

- [ ] **Step 2: Dry-run production compose render**

Run:
```bash
API_IMAGE=ghcr.io/example/fasttravel-api:sha \
BOT_IMAGE=ghcr.io/example/fasttravel-bot:sha \
SCHEDULER_IMAGE=ghcr.io/example/fasttravel-scheduler:sha \
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```
Expected: exit 0.

- [ ] **Step 3: Post-deploy smoke**

Run on VPS after deploy:
```bash
curl -fsS https://api.fasttravel.com.ua/health
curl -fsS https://api.fasttravel.com.ua/robots.txt
curl -fsS https://api.fasttravel.com.ua/sitemap.xml | head
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=120 api bot scheduler nginx
gh workflow run browser-smoke.yml -f base_url=https://fasttravel.com.ua
```
Expected: health is ok; SEO endpoints return 200; app containers stay up; no error loop in logs.

---

## Self-Review

- Spec coverage: covers the user-requested production push: bot/channel truth, frontend truth, runtime drift, observability, CI/deploy, secrets, data quality, and VPS cutover.
- Placeholder scan: there are no `TBD` or vague "add tests" entries; each task has files and commands.
- Type consistency: env names are consistent across frontend (`NEXT_PUBLIC_TELEGRAM_CHANNEL_URL`) and backend (`TELEGRAM_CHANNEL_ID`); compose image vars are `API_IMAGE`, `BOT_IMAGE`, `SCHEDULER_IMAGE`.
