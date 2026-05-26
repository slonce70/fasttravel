# Testing

## Quick reference

All tests run inside Docker via the `docker-compose.test.yml` overlay so dev
machines don't need Python/Poetry installed for the right versions. The overlay
flips `INSTALL_DEV=true` on each app's Dockerfile, which installs pytest +
fakeredis on top of the production deps.

### One-time setup (after deps change or first checkout)

```bash
# Build the test images for api, scheduler, and bot. Required only when:
#   - first checkout
#   - pyproject.toml / Dockerfile changes
#   - you switched branches with diverging deps
docker compose -f docker-compose.yml -f docker-compose.test.yml build api-test scheduler-test bot-test
```

### Run a test suite

```bash
# Start the dependencies first (postgres, redis).
docker compose up -d postgres redis

# Run a full app suite (api, scheduler, ingest, bot)
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test pytest
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps scheduler-test pytest
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps bot-test pytest

# Single file or single test:
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm \
  --no-deps scheduler-test pytest tests/test_sitemap_long_tail.py -v

docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm \
  --no-deps scheduler-test pytest tests/test_sitemap_long_tail.py::test_never_raises -v
```

### apps/ingest

The ingest tests have their own venv (`apps/ingest/.venv`) wired with VCR
cassettes, fakeredis, and httpx-mock — they don't need the test overlay:

```bash
cd apps/ingest
.venv/bin/python -m pytest tests/ -v
```

## DB-touching tests

apps/api tests use SAVEPOINT + ROLLBACK per test (see `apps/api/tests/conftest.py`)
so they need a real Postgres at `postgres:5432` with the role `fasttravel`. The
test compose overlay inherits this from `docker-compose.yml` where the role is
created by the `postgres` service's init script (POSTGRES_USER=fasttravel).

Common gotcha: if you see `role "fasttravel" does not exist`, the postgres
volume was created with a different `POSTGRES_USER`. Recreate it:

```bash
docker compose down -v   # ⚠️  wipes pg_data — only safe in dev
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
```

## Running locally without Docker

If you want to iterate quickly outside Docker, each app's `.venv` works:

```bash
cd apps/scheduler
PYTHONPATH=$(pwd)/.. .venv/bin/python -m pytest tests/ -v
```

The `PYTHONPATH=$(pwd)/..` is needed so `from shared.publishers...` resolves
to `apps/shared/publishers/`. `DATABASE_URL` env can stay unset for
scheduler/ingest unit tests because the engine is built lazily.

For apps/api, you do need Postgres + Redis reachable:

```bash
docker compose up -d postgres redis
cd apps/api
DATABASE_URL=postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@localhost:5432/fasttravel \
  REDIS_URL=redis://localhost:6379/0 \
  .venv/bin/python -m pytest tests/ -v
```

## CI

CI uses the same Dockerfile with `INSTALL_DEV=true` baked into the test
workflow. See `.github/workflows/ci.yml`. Local and CI should produce identical
test outputs because they share both the Dockerfile and the lockfiles.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'pytest'` | Built without dev deps | Re-build with the test overlay (`-f docker-compose.test.yml`) |
| `ModuleNotFoundError: No module named 'fakeredis'` | Scheduler image is old | Re-build scheduler test image |
| `ModuleNotFoundError: No module named 'shared.publishers'` | PYTHONPATH not set | Use the compose overlay (`PYTHONPATH=/app` is baked in) |
| `role "fasttravel" does not exist` | Postgres volume from a previous tenant | `docker compose down -v && docker compose up -d postgres` |
| `connection to server at "postgres" failed: ... could not translate host name` | Running locally without compose, host expects "postgres" hostname | Override `DATABASE_URL` to use `localhost` (see above) |
| Tests pass locally but fail in CI | Lockfile drift | Run `poetry lock --no-update` inside the app dir, commit |
