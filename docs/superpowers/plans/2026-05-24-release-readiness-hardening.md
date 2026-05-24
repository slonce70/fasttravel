# FastTravel Release Readiness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bring the current FastTravel working tree from "locally alive but release-blocked" to a verifiable release candidate for backend scheduler/API and frontend.

**Architecture:** Fix the smallest release blockers first, then harden the runtime contracts that were misleading in the audit: scheduler ingest startup semantics, production proxy routing, SEO endpoints, and deploy/test gates. Keep existing real-data behavior intact and avoid introducing synthetic data.

**Tech Stack:** Python 3.12, FastAPI, APScheduler, SQLAlchemy/Alembic, Postgres, Redis, Next.js 15, pnpm, Docker Compose, nginx.

---

## File Map

- `apps/web/src/components/HotelCard.tsx`: fix invalid ESLint disable comment that breaks `next build`.
- `apps/web/src/components/DealCard.tsx`: suppress the same intentional plain-image rule consistently.
- `apps/api/tests/test_seed.py`: remove obsolete test that imports deleted synthetic seed code.
- `apps/scheduler/src/main.py`: register weekly sitemap ingest plus explicit startup one-shot job.
- `apps/scheduler/tests/test_smoke.py`: assert scheduler wiring includes sitemap jobs.
- `infra/nginx/fasttravel.conf`: use Docker service DNS in containerized production nginx.
- `apps/api/src/routers/seo.py`: add `robots.txt` and `sitemap.xml` endpoints from real DB content.
- `apps/api/src/routers/__init__.py`: export router package normally if needed.
- `apps/api/src/main.py`: include SEO router.
- `apps/api/tests/test_seo.py`: cover robots and sitemap behavior without fake data.
- `.github/workflows/ci.yml`: ensure API tests run without obsolete synthetic seed assumptions if needed.

## Task 1: Fix Frontend Build Blocker

**Files:**
- Modify: `apps/web/src/components/HotelCard.tsx`
- Modify: `apps/web/src/components/DealCard.tsx`

- [x] **Step 1: Reproduce build/lint failure**

Run:
```bash
cd apps/web
pnpm lint
pnpm build
```
Expected before fix: FAIL with `Definition for rule '@next/next/no-img-element - Cloudflare Pages' was not found`.

- [x] **Step 2: Fix ESLint directive**

Use this exact directive above each intentional `<img>`:
```tsx
{/* eslint-disable-next-line @next/next/no-img-element */}
```
or for non-JSX comment position:
```tsx
// eslint-disable-next-line @next/next/no-img-element
```
Put explanatory text on a separate normal comment line.

- [x] **Step 3: Verify frontend**

Run:
```bash
cd apps/web
pnpm lint
pnpm typecheck
pnpm build
```
Expected after fix: all commands exit 0.

## Task 2: Remove Obsolete Synthetic Seed Test

**Files:**
- Delete: `apps/api/tests/test_seed.py`

- [x] **Step 1: Reproduce API collection failure**

Run:
```bash
docker compose exec -T api python -m pytest
```
Expected before fix: FAIL during collection with `ModuleNotFoundError: No module named 'scripts.seed_demo'`.

- [x] **Step 2: Delete stale test**

Remove `apps/api/tests/test_seed.py`; `apps/api/scripts/README.md` already documents that synthetic seed scripts were removed.

- [x] **Step 3: Verify API tests**

Run the API test command available in this checkout:
```bash
uv run --directory apps/api --group dev pytest
```
Fallback when local dependency resolution is unavailable:
```bash
docker compose exec -T api python -m pytest
```
Expected after fix: tests collect and pass, or any remaining failure is a real behavior failure to fix next.

## Task 3: Make Sitemap Ingest Startup Semantics Honest

**Files:**
- Modify: `apps/scheduler/src/main.py`
- Modify: `apps/scheduler/tests/test_smoke.py`

- [x] **Step 1: Add scheduler wiring test**

Add a test that builds `_build_scheduler()` and asserts these job ids exist:
```python
expected = {
    "sitemap_long_tail_ingest",
    "sitemap_long_tail_ingest_startup",
}
assert expected.issubset({job.id for job in scheduler.get_jobs()})
```

- [x] **Step 2: Run test and verify RED**

Run:
```bash
uv run --directory apps/scheduler --group dev pytest tests/test_smoke.py -q
```
Expected before implementation: FAIL because `sitemap_long_tail_ingest_startup` is missing.

- [x] **Step 3: Register startup one-shot**

In `apps/scheduler/src/main.py`, import `DateTrigger`, compute a near-future UTC run date, and add:
```python
scheduler.add_job(
    sitemap_long_tail_ingest,
    DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=30), timezone=TIMEZONE),
    id="sitemap_long_tail_ingest_startup",
    name="sitemap_long_tail_ingest (startup one-shot resume)",
)
```
Keep weekly cron unchanged.

- [x] **Step 4: Verify scheduler tests**

Run:
```bash
uv run --directory apps/scheduler --group dev pytest
```
Expected: all scheduler tests pass.

## Task 4: Fix Containerized Production Nginx Routing

**Files:**
- Modify: `infra/nginx/fasttravel.conf`

- [x] **Step 1: Inspect current proxy targets**

Run:
```bash
rg -n "127\\.0\\.0\\.1:(8000|3001)" infra/nginx/fasttravel.conf
```
Expected before fix: matches API and Grafana proxy targets.

- [x] **Step 2: Replace container-local loopback**

Use Docker service DNS:
```nginx
proxy_pass http://api:8000;
proxy_pass http://grafana:3000/;
proxy_pass http://grafana:3000/api/live/;
```

- [x] **Step 3: Verify config shape**

Run:
```bash
rg -n "127\\.0\\.0\\.1:(8000|3001)" infra/nginx/fasttravel.conf
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/tmp/fasttravel-prod-compose.yml
```
Expected: no loopback matches; compose config renders.

## Task 5: Add Real SEO Endpoints

**Files:**
- Create: `apps/api/src/routers/seo.py`
- Modify: `apps/api/src/main.py`
- Create: `apps/api/tests/test_seo.py`

- [x] **Step 1: Write tests**

Test `/robots.txt` includes a sitemap URL and `/sitemap.xml` returns XML with real active hotel slugs from the test transaction. Insert a minimal destination and hotel row in the test, then request sitemap via the ASGI client.

- [x] **Step 2: Verify RED**

Run:
```bash
uv run --directory apps/api --group dev pytest tests/test_seo.py -q
```
Expected before implementation: FAIL with 404.

- [x] **Step 3: Implement router**

Create a FastAPI router with:
- `GET /robots.txt`: plain text, `User-agent: *`, `Allow: /`, `Sitemap: https://fasttravel.com.ua/sitemap.xml`
- `GET /sitemap.xml`: XML response generated from active hotels with non-null `canonical_slug`, ordered by id, capped at 50,000 URLs.

- [x] **Step 4: Wire router**

Import and include `seo.router` in `apps/api/src/main.py`.

- [x] **Step 5: Verify API**

Run:
```bash
uv run --directory apps/api --group dev pytest
curl -fsS http://localhost:8000/robots.txt
curl -fsS http://localhost:8000/sitemap.xml
```
Expected: tests pass; local running API returns 200 for both endpoints after container rebuild/restart if needed.

## Task 6: Final Release Verification

**Files:**
- No direct code files; this is the verification gate.

- [x] **Step 1: Python checks**

Run:
```bash
uv run --directory apps/api --group dev pytest
uv run --directory apps/scheduler --group dev pytest
```

- [x] **Step 2: Frontend checks**

Run:
```bash
cd apps/web
pnpm lint
pnpm typecheck
pnpm build
```

- [x] **Step 3: Runtime smoke**

Run:
```bash
docker compose up -d --build api scheduler
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/api/search?limit=1
curl -fsS http://localhost:8000/robots.txt
curl -fsS http://localhost:8000/sitemap.xml
docker compose logs --tail=80 scheduler
```

- [x] **Step 4: Git sanity**

Run:
```bash
git diff --check
git status --short
```

---

## Self-Review

- Spec coverage: covers audit blockers: frontend build, API tests, scheduler ingest startup, prod nginx, SEO endpoints, final verification.
- Placeholder scan: no TBD/implement-later placeholders remain.
- Type consistency: tests and implementation use existing FastAPI/SQLAlchemy/pytest patterns.

## Execution Notes

- Completed on branch `codex/release-hardening`.
- Runtime verification avoided `docker compose up -d --build` because a long-running manual sitemap ingest is active in `ft_scheduler`; restarting the scheduler would kill the process. The replacement verification path was: build API/scheduler images, run API/scheduler tests against current source, check live `/health` and `/api/search`, and verify SEO endpoints through tests plus a temporary ASGI runtime.
- Docker Desktop's credential helper hung during normal BuildKit metadata resolution. Image builds were verified with a temporary empty `DOCKER_CONFIG`; this is a local Docker setup issue, not an application code failure.
