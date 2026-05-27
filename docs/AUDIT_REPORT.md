# FastTravel — повний аудит проекту

**Дата:** 2026-05-26
**Глибина:** глибокий аудит — 4 паралельних агенти + автоматичні сканери (gitleaks, pip-audit, npm/pnpm audit, ruff, mypy, hadolint, yamllint, bandit, detect-secrets)
**Огляд:** аудит покриває архітектуру, безпеку, тести/якість, DevOps/інфру. ~134 знахідки, з яких 9 Critical/High потребують уваги цього тижня.

> Інтерактивна таблиця всіх знахідок із сортуванням і фільтрацією — див. **artifact "FastTravel audit findings"** у Cowork sidebar.

---

## TL;DR — стан проекту

**FastTravel — добре спроектований MVP**, помітно зрілий для одноосібного проекту на free-tier інфрі. Сильні сторони — async-дисципліна (немає блокувального I/O в async-шляхах, `asyncio.run` лише в `__main__`), послідовна error-handling (50 `except Exception`, всі логують або re-raise), типізований API client на фронті, server-first Next.js App Router (лише 10/40 client components), 332-рядковий `production-preflight.sh` що перевіряє інваріанти між файлами, реальний `backup-restore-drill.sh` (а не `pg_dump` і молись), Dependabot на всі екосистеми, AlertManager → Telegram pipeline.

**Найгостріші болі — три кластери:**

1. **AuthN-by-convention замість AuthN-by-enforcement.** AlertManager-вебхук *може* перевіряти секрет, але мовчки приймає запити коли env-var порожній; Grafana defaults to `admin:admin` якщо оператор забуде; rate-limiter обіцяє per-IP а реально per-nginx-IP (один користувач блокує всіх).
2. **CVE-дрейф у Python-залежностях.** 44 унікальних вразливості: aiohttp 3.10/3.12 (38 CVE, fix у 3.13.4), starlette 0.46.2 (3 CVE), python-multipart 0.0.20 (3 CVE), urllib3 1.26.20 (5 CVE), curl-cffi 0.7.4 (1 CVE). pip-audit запускається лише раз на тиждень → до 7 діб експозиції.
3. **Контейнерні гайдрейли відсутні.** Жоден сервіс не має ротації логів, лімітів пам'яті, retention для Prometheus — будь-яка з цих проблем може забити 200 GB boot-диск або тригернути OOM-killer і покласти Postgres разом з усім.

**Що зроблено добре і не треба чіпати:** SQL завжди параметризований; CORS правильно вузький (no credentials); `.env` ніколи не комітився (історія чиста); немає `pull_request_target`-footgun у CI; немає bare `except:`; frontend dep tree чистий (0 CVE); ruff (0.7.4) проходить без помилок у всіх 4-х Python сервісах; немає блокувальних викликів в async-коді; немає secrets у git-історії.

---

## 🚨 Топ-9 критичних/високих проблем — виправити цього тижня

| # | Severity | Категорія | Сервіс | Проблема |
|---|---|---|---|---|
| 1 | **CRITICAL** | Secrets | cross-cutting | Живий `TELEGRAM_BOT_TOKEN` і `ALERTMANAGER_WEBHOOK_SECRET` лежать у локальному `.env`. Гітом не трекаються, але читаються Spotlight/Time Machine/IDE-плагінами/будь-яким процесом з shell-доступом — включно з агентом цього аудиту. **Вважати скомпрометованими, ротувати.** |
| 2 | **HIGH** | AuthN | bot | `apps/bot/src/alert_webhook.py:92-106` — якщо `ALERTMANAGER_WEBHOOK_SECRET` порожній або не встановлений, перевірка секрету повністю обходиться (`if secret: …`). У `apps/bot/src/config.py` `assert_prod_secrets()` не вимагає цього секрету. Атакувальник з доступу до контейнерної мережі може спуфити алерти у Telegram-канал оператора. |
| 3 | **HIGH** | Containers | cross-cutting | `docker-compose.prod.yml` не має `ports: !reset []` для `alertmanager` → порт **9093 публічно опублікований у проді**. Анонімний інтернет-юзер бачить усі firing-алерти (PII у мітках), може silence'нути їх, або зробити DoS вашій on-call ротації. |
| 4 | **HIGH** | Deps | bot, scheduler | aiohttp 3.10.11 (bot) → 19 CVE; aiohttp 3.12.15 (scheduler) → 18 CVE. Включно з parser-confusion (CVE-2024-52303), request smuggling (CVE-2025-53643). Bot's `/alerts` webhook — це aiohttp.web на мережевому порті. **Fix:** `aiohttp ≥ 3.13.4`. |
| 5 | **HIGH** | Deps | api, ingest | `starlette==0.46.2` (3 CVE, fix у 1.0.1), `python-multipart==0.0.20` (3 CVE), `urllib3==1.26.20` транзитивно в ingest (5 CVE), `curl-cffi==0.7.4` (1 CVE). FastAPI стоїть на starlette → публічно експоновано. |
| 6 | **HIGH** | Postgres / Backups | infra | `archive_mode=off` → **немає WAL-архівування, немає PITR**. RPO ≈ 24 год (єдиний бекап — нічний `pg_dump → R2`). Краш о 23:59 = втрата дня даних. + дампи у R2 **незашифровані** — компрометована R2-токен = повний дамп БД у відкритому вигляді. |
| 7 | **HIGH** | CI / Coverage | api | `ci.yml` запускає `pytest --cov=src` але `pytest-cov` НЕ задекларовано в dev-deps `apps/api`. Крок мовчки падає → coverage не вимірюється. Інші сервіси (scheduler/bot/ingest) взагалі не мають `--cov`. |
| 8 | **HIGH** | Compose / Cost | cross-cutting | Жодна служба не має `logging:` секції → docker default `json-file` без `max-size` → логи забивають 200 GB boot-диск через місяці. + жодна служба не має `mem_limit:` у prod overlay → runaway-контейнер може OOM-килнути Postgres. |
| 9 | **HIGH** | Nginx | infra | certbot встановлений через `cloud-init.yml`, але **renewal hooks НЕ написані** і `certbot.timer` не enable'нутий. LE-cert живе 90 днів → залежить від пам'яті оператора. Виявиться як 5xx з фронта в один день. |

---

## Загальна статистика

| Метрика | Значення |
|---|---|
| Python LOC (apps/{api,bot,scheduler,ingest,shared}) | 22,390 |
| TypeScript/TSX LOC (apps/web/src) | 4,495 |
| Python test files | 221 (~6,000 LOC) |
| TS/JS test files | 2 (4 unit + 7 e2e) |
| Ruff violations | 0 (всі 4 Python сервіси чисті) |
| Hadolint findings | 5 (всі DL3008 — unpinned apt-get) |
| Mypy в CI | `continue-on-error: true` + `\|\| true` → не enforced |
| pip-audit total CVE | 47 (api:7, bot:19, scheduler:19, ingest:2) |
| pnpm audit (web) | 0 vulns, 848 deps |
| Bandit MED/HIGH | 6 (1 HIGH MD5, 5 MED — переважно `0.0.0.0` bind) |
| gitleaks (git history) | 0 leaks |
| gitleaks (working tree) | 65 (всі у build-output `.vercel/`, `.open-next/` — false positive) |
| TODO/FIXME у власному коді | 1 |
| Bare `except:` | 0 |

---

## Розділ 1 — Архітектура та код

### 1.1 Сильні сторони

- **Async-дисципліна.** Жодного `time.sleep`/sync `requests`/missing-await; `asyncio.run` лише на `__main__` entrypoints. Коментарі пояснюють вибір concurrency (semaphore widths, `AUTOCOMMIT` для `REFRESH MV CONCURRENTLY`, BRPOP timeout для clean shutdown).
- **Frontend boundaries.** Server-first App Router, 10/40 client components (`use client` обґрунтовано), типізований `apiFetch<T>`, TanStack Query з sensible defaults, TypeScript `strict: true` з `noUncheckedIndexedAccess`.
- **Observability вбудована від початку.** Prometheus metrics з deliberate buckets, structlog із correlation IDs, AlertManager → Telegram bridge, partition-cleanup metrics — не bolted on.
- **Error handling.** 50 `except Exception` — усі логують або re-raise з `# noqa: BLE001` і пояснювальним коментарем. Нуль `except:`. Нуль silent swallows.
- **Міграції.** Reversible, добре закоментовані, з міркуваннями (e.g. UNIQUE constraint на price_observations).

### 1.2 Найгостріші болі

**[Medium] Cross-cutting duplication of infra plumbing.** `apps/{api,bot,scheduler}/src/config.py` — три класи Settings з copy-paste `forbidden_markers = ("_change_me", "fasttravel_dev")` і дрейфом (scheduler перевіряє Telegram creds, API — ні). Те саме з `infra/sentry.py` (бот не має `SqlalchemyIntegration` хоч і ходить у Postgres) і `infra/logging.py`. `apps/shared/` існує, але містить лише Telegram publisher.
→ **Fix:** Винести `BaseAppSettings`, `configure_logging`, `configure_sentry` у `apps/shared/infra/`. Single-highest-impact рефактор.

**[Medium] `apps/scheduler/src/jobs/snapshot_farvater.py` (1,284 LOC) і `detect_deals.py` (700 LOC) — моноліти.** Перший змішує regex-екстрактори, HTTP catalog walker, hotel upsert, price-validation insert, MV refresh, freshness metric, entrypoint. Другий містить 5 SQL-стратегій з ручною budget-арифметикою повтореною 4 рази.
→ **Fix:** Розбити на `clients/farvater_catalog.py`, `services/{hotel_upsert,price_insert}.py`, `jobs/snapshot_farvater.py` (тільки orchestration). Для detect_deals — `class DealStrategy` + `for s in strategies: ...`.

**[Medium] `apps/bot` — другий клас.** Немає `pyproject.toml` (deps пінняться лише в Dockerfile, без lockfile), `apps/bot/src/infra/db.py` робить raw `text(...)` SQL для subscriber CRUD хоча в API вже є ORM-модель `TelegramSubscriber`, `search_wizard.py` (434 LOC) змішує FSM dispatch + рендеринг + пагінацію + API client + UTM URL construction.
→ **Fix:** Додати `apps/bot/pyproject.toml`; використати існуючий `TelegramSubscriber` ORM; розбити wizard на `wizard/steps/{country,nights,when,budget,meal,stars}.py`.

### 1.3 Дивні/несподівані знахідки

- **[High] `/api/search` приймає `?amp;param=...` aliases** (`apps/api/src/routers/search.py:73-105`) — workaround для buggy `&amp;` у query strings, що подвоює route signature і невидимий в OpenAPI. **Fix:** ASGI middleware що rewrite'ить `amp;` перед матчингом роуту.
- **[Medium] GET `/api/hotels/{id}/calendar` мутує Redis state** (`apps/api/src/routers/hotels.py:127`) — `_spawn_fire_and_forget(_bump_hot_counter(...))` на кожен GET. Порушує semantics, ламає CDN-кешування, module-level `_pending_tasks: set` може непомітно рости при Redis-outage.
- **[Medium] `_maybe_await_redis` хак** (`apps/api/src/routers/hotels.py:70-73`) — повторюється у scheduler як `cast(Awaitable[int], ...)`. Два різних workaround для однієї проблеми типізації `redis.asyncio` в двох сервісах.
- **[Medium] `routers/hotels.py` (277 LOC) — 4 concerns:** CRUD, calendar, offers, refresh-queue з Redis dedup/cap/farvater mapping inline. **Fix:** Виокремити `services/refresh_queue.py`.
- **[Low] `Hotel.coords` — `Text` замість PostGIS POINT.** Перший хто захоче "знайти готелі поряд" виявить що колонка не індексована.
- **[Low] `Hotel.review_score` типізована як `float`, насправді `Decimal`** (`Numeric(3,1)` + анотація `float | None` — SQLAlchemy повертає Decimal).
- **[Low] React 19 RC + `@types/react ^18.3.12`** — React 19 стабільний на момент аудиту, frontend крутиться на 6-місячному RC build з 18-version typings.

### 1.4 Повний список (32 знахідки) — див. артефакт

---

## Розділ 2 — Безпека

### 2.1 Топ-5 найгостріших

(дублюються з топ-9 вище: #1 token у .env, #2 webhook bypass, #3 alertmanager порт, #4-5 CVE в deps).

### 2.2 Інші важливі (Medium)

- **[Medium] Webhook secret порівнюється через `!=`, не constant-time** (`apps/bot/src/alert_webhook.py:104`). Timing side-channel.
  → **Fix:** `hmac.compare_digest(...)` + rate-limit 401 responses.

- **[Medium] slowapi rate limiter — keying НЕ per-IP за nginx.** `apps/api/src/infra/limiter.py:18-20` використовує `get_remote_address` що повертає `request.client.host`. У проді всі запити йдуть через nginx → ліміт `10/hour` на `/api/hotels/{id}/refresh` стає глобальним або keying на CF-egress IP.
  → **Fix:** Custom `key_func` що читає `CF-Connecting-IP` → `X-Forwarded-For[0]` → `client.host`. Додати тест.

- **[Medium] Frontend на Cloudflare Workers без CSP / X-Frame-Options / HSTS.** `apps/web/next.config.mjs` не має `headers()`. Nginx має ці хедери для API, але сайт — на іншому хості і без захисту.

- **[Medium] CSP intentionally omitted on nginx** (`infra/nginx/fasttravel.conf:96-97`) — коментар "easy to break Next.js", але nginx обслуговує API, не фронт. CSP на JSON-API безпечна і ловить рендер інжектованого HTML на error-page.

- **[Medium] Postgres listens on `0.0.0.0`, no SSL.** `infra/postgres/postgresql.conf:6 listen_addresses = '*'`. Inter-container traffic незашифрований. Acceptable на bare-metal docker bridge, але silently breaks при міграції на swarm/k8s.

- **[Medium] Grafana default `admin:admin`.** `docker-compose.yml:203` має fallback `${GRAFANA_ADMIN_PASSWORD:-admin}`. Захист — лише `production-preflight.sh` (запускається в CI strict mode).
  → **Fix:** `${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD required}`.

- **[Medium] Bot Dockerfile як root, single-stage, no HEALTHCHECK.** Контраст з api/scheduler що мають `USER app`.

- **[Medium] Дампи бази на R2 незашифровані** — R2 server-side encryption з Cloudflare-managed keys → leaked token = plaintext всіх dump'ів (включно з subscriber chat_id, filters — PII).
  → **Fix:** `| age -r <recipient>` між gzip і rclone upload.

- **[Medium] Bandit HIGH: MD5 в `apps/ingest/src/dedup.py:43`.** Для dedup-ключа, не для security.
  → **Fix:** `hashlib.md5(..., usedforsecurity=False)`.

### 2.3 Залежності (повний список pip-audit)

#### apps/api (7 CVE)
- `starlette 0.46.2` → CVE-2025-54121 (fix 0.47.2), CVE-2025-62727 (0.49.1), PYSEC-2026-161 (1.0.1)
- `python-multipart 0.0.20` → CVE-2026-24486 (0.0.22), CVE-2026-40347 (0.0.26), CVE-2026-42561 (0.0.27)
- `pytest 8.4.2` → CVE-2025-71176 (9.0.3) — dev-only

#### apps/scheduler (19 CVE)
- `aiohttp 3.12.15` → 18 CVE (всі fixed in 3.13.4): CVE-2025-69223…30, CVE-2026-22815, CVE-2026-34513…25
- `pytest 8.4.2` → CVE-2025-71176

#### apps/bot (19 CVE)
- `aiohttp 3.10.11` (transitive of aiogram 3.13.1) → 19 CVE (mix CVE-2024-52303 parser confusion, CVE-2025-53643 request smuggling, etc.) — fix 3.13.4

#### apps/ingest (2 CVE)
- `urllib3 1.26.20` → CVE-2025-50181, CVE-2026-21441, CVE-2025-66418, CVE-2025-66471, PYSEC-2026-141 (fix `^2.7.0`)
- `curl-cffi 0.7.4` → CVE-2026-33752 (fix 0.15.0)

#### apps/web (0 CVE) — clean ✓

### 2.4 CI/CD security

- **[Low] Unpinned actions** (`@v4`, `@v6`, etc.) — supply-chain risk (tj-actions/changed-files-style incident).
  → **Fix:** Pin до commit SHA, документувати у CODEOWNERS.
- **[Low] `ssh-keyscan` TOFU fallback** у `deploy-api.yml` і `daily-backup.yml` — MITM на першому run sticks forever.
  → **Fix:** Зробити `DEPLOY_SSH_KNOWN_HOSTS` обов'язковим.
- **[Low] `pip-audit` лише на тижневому cron** (security-scan.yml) — до 7 днів експозиції.
  → **Fix:** Додати fast `pip-audit` step у per-PR `ci.yml`.
- **[Low] `tr -d '=+/\\n'` у secrets-bootstrap.sh** зменшує alphabet base64 з 66 до 63 chars, документовані "32 байти" вводять в оману. → `openssl rand -hex 32`.

---

## Розділ 3 — Тести та якість коду

### 3.1 Картина по сервісах

| Service | Source LOC | Test files | Tests | Test:Src | Ruff | Mypy CI | Coverage |
|---|---:|---:|---:|---:|---|---|---|
| api | 3,080 | 13 | 61 | 0.71 | 0 errors | strict, **continue-on-error** | **broken (no pytest-cov)** |
| bot | 2,756 | 8 | 41 | 0.27 | 0 errors | **not run** | none |
| scheduler | 6,346 | 20 | 122 | 0.41 | 0 errors | strict, `\|\| true` | none |
| ingest | 1,613 | 4 | 11 | 0.15 | 0 errors | strict, `\|\| true` | none |
| web | 4,495 | 1+1 | **4+7** | **0.03** | eslint | tsc strict | none |
| shared | small | 0 | 0 | 0.0 | n/a | n/a | none |

### 3.2 Найгостріші проблеми

- **[High] CI coverage step падає мовчки** (api: `pytest --cov=src` без `pytest-cov` у deps).
- **[High] Bot CI робить raw `pip install` з пінами повтореними у Dockerfile + CI workflow** — triple source of truth.
- **[High] Scheduler/ingest/bot — нуль coverage**. Scheduler — найбільший сервіс і має 0 видимості над тим, які гілки покривають його 122 тести.
- **[High] Mypy `strict=true` у pyproject + `continue-on-error: true` + `|| true` у CI** — типізація обіцяна, не enforced. Найгірше з обох світів.
- **[High] Frontend — 4 unit + 7 e2e тести на 4,500 LOC.** Vitest конфіг навіть не матчить `.tsx`. Recharts-календар, deal cards, search wizard — нуль тестів.
- **[Medium] `pytest-vcr`/`vcrpy`/`respx` задекларовані в ingest — нуль cassettes** (`find apps/ingest/tests -path '*cassettes*'` → пусто). Dead infra.
- **[Medium] Скрипти heavy mocks замість real DB+Redis** у scheduler/ingest tests — circular validation (моки повертають що тест очікує).
- **[Medium] No pre-commit/husky/lefthook** — devs пушать lint/typecheck failures у CI.
- **[Medium] No pytest-xdist** — sequential execution scales linearly.
- **[Medium] Scheduler CI без Postgres+Redis services block** — `detect_deals` і `post_deals` (1000 LOC core логіки) без SQL-level integration tests, документація обіцяє `tests/integration/` якого не існує.

### 3.3 Що зроблено добре

- API SAVEPOINT-per-test fixture (`apps/api/tests/conftest.py`) — exemplary, з пояснюючим коментарем про asyncpg event-loop quirks.
- Farvater HTTP client tests покривають breaker/cap/throttle paths з thoughtful assertions.
- Schema canary tests ловлять exact contract-break який canary будувався ловити.
- Нуль `@pytest.mark.skip` без обґрунтування. Нуль `assert True` placeholders.
- Ruff 0.7.4 (pinned CI version) чистий у всіх 4 сервісах.

---

## Розділ 4 — DevOps та інфраструктура

### 4.1 Quick wins (≤1 година кожна)

1. **Додати `logging:` driver caps до всіх служб** у `docker-compose.yml` через YAML anchor — інакше docker default `json-file` без `max-size` забиває 200 GB диск.
2. **Pin Docker base images до patch/digest** — `python:3.12-slim-bookworm`, `redis:7-alpine`, `nginx:1.27-alpine` усі float. Dependabot Docker ecosystem вже налаштований.
3. **Prometheus retention flags** — `--storage.tsdb.retention.time=30d --storage.tsdb.retention.size=8GB`. Default — 15 днів без size cap.
4. **`mem_limit:` у prod overlay** — постгрес 6g, redis 768m, api 1g, bot/scheduler 512m, prometheus 1g, grafana 512m, nginx 128m.
5. **Drop `:latest` tags у `deploy-api.yml`** (тільки `sha-<short>`) — інакше rollback ламається коли VPS pull'ає `latest`.

### 4.2 Найгостріші проблеми

(критичні дублюються з топ-9: AlertManager порт, certbot renewal, лімітів немає, WAL archiving off).

**[High] Terraform local state, не remote.** `infra/terraform/main.tf:23-37` — S3 backend block закоментований ("Phase 2"). State живе тільки на лептопі оператора. Bus-factor = 1.

**[Medium] Bot Dockerfile: no pyproject, no lockfile, no multi-stage, no USER app.** Транзитивні deps анпіннуть; CI workflow дублює піни. Bot не в Dependabot pip ecosystem.

**[Medium] Prometheus має лише 4 scrape targets — немає node_exporter/postgres_exporter/redis_exporter.** Більшість outages на маленьких VM-ах — infra-level, не app-level. Немає `DiskFull80Pct`, `OOMRiskHigh`, `PostgresDeadTuplesHigh`.

**[Medium] Postgres: pg_stat_statements не loaded.** Коли snapshot почне займати 60 хв замість 20, не буде per-statement IO timing.

**[Medium] Postgres `max_connections=100` vs application pools.** API+scheduler+bot async pools + snapshot bursts at concurrency=80 → може punch through 100 → `OperationalError: too many clients`.

**[Medium] pg_dump у plain SQL format (не `-Fc`)** — restore single-threaded, `pg_restore -j N` неможливий. Впливає на RTO.

**[Medium] No log aggregation.** Stdout → docker logs → `/var/lib/docker/containers/*-json.log` (without rotation per Q1). Debug issue з 3 днів тому = SSH+grep, hoping logrotate didn't truncate. Single biggest observability gap.

**[Medium] No unattended-upgrades у cloud-init.** OS-level CVE не патчаться автоматично.

**[Medium] `:latest` tags pushed alongside `sha-<short>`** — defeats image-pin rollback.

**[Medium] deploy-api.yml немає `needs: [ci]`** — `Deploy API` стартує паралельно з CI на тому ж коміті. Test failure не блокує деплой.

### 4.3 Low/Info

Багато (див. артефакт): no SBOM/cosign, no tflint у CI, no Dockerfile lint у CI, plaintext SSH ingress 0.0.0.0/0 default, RPO/RTO не документовані, R2 single-region, hadolint DL3008 ×5 (unpinned apt-get).

---

## Recommended action plan

### Цього тижня (~4-6 годин роботи)

1. **Ротувати Telegram bot token + AlertManager webhook secret** (вважати скомпрометованими). Згенерувати нові через `@BotFather` + `openssl rand -hex 32`.
2. **Закрити AlertManager порт у prod** — додати `ports: !reset []` у `docker-compose.prod.yml` для `alertmanager`.
3. **Виправити webhook auth bypass:**
   - `apps/bot/src/config.py` — додати `alertmanager_webhook_secret` у `assert_prod_secrets()` offenders list.
   - `apps/bot/src/alert_webhook.py:104` — `hmac.compare_digest(...)` замість `!=`.
   - У prod fail-closed коли env-var відсутній.
4. **One coordinated PR для CVE-bump:** `aiohttp>=3.13.4` (через bump aiogram), `starlette>=1.0.1`, `python-multipart>=0.0.27`, `urllib3>=2.7.0`, `curl-cffi>=0.15.0`, `pytest>=9.0.3`.
5. **Encrypt R2 backups** — `| age -r <recipient>` у `.github/workflows/daily-backup.yml`; ротувати R2 token.
6. **Fix coverage gate** — `poetry add --group dev pytest-cov` у api/scheduler/ingest/bot.

### Цей спринт (~1-2 тижні)

7. **Cross-cutting refactor:** винести `BaseAppSettings`, `configure_logging`, `configure_sentry`, Redis singleton у `apps/shared/infra/`. Усуне дрейф між api/bot/scheduler.
8. **Add `apps/bot/pyproject.toml`** + Poetry lockfile; multi-stage Dockerfile; `USER app`; додати bot у Dependabot і pip-audit matrix.
9. **Container guardrails:** `logging:` anchor + `mem_limit:` у prod overlay + Prometheus retention flags.
10. **Certbot renewal hooks** у `cloud-init.yml` + enable `certbot.timer`.
11. **Mypy decision:** або ratchet (record current error count, fail CI if grows), або drop `strict=true`. Не залишати "strict-but-unenforced".
12. **Add `services: postgres + redis` block у scheduler CI job** + написати `tests/integration/test_detect_deals_sql.py` (живий DB замість мокованої сесії).
13. **Vitest + @testing-library/react** для apps/web — стартові тести для `PriceCalendar`, `DealCard`, search wizard.

### Цей квартал

14. **Split `snapshot_farvater.py` (1284 LOC) і `detect_deals.py` (700 LOC)** на тонкий job + services + clients.
15. **WAL archiving до R2** (або документувати 24h RPO як accepted risk).
16. **Log aggregation** — Grafana Loki / Better Stack free tier + promtail/vector sidecar.
17. **node_exporter + postgres_exporter + redis_exporter** + 4 host-level alerts.
18. **Frontend security headers** — `headers()` block у `next.config.mjs` (CSP + HSTS + X-Frame-Options + Referrer-Policy).
19. **Terraform remote state** у R2 + state lock.
20. **Pin GitHub Actions до commit SHA** + automation.
21. **Pre-commit/lefthook config** — ruff, pnpm typecheck, prettier.

---

## Цифри для контексту

- ~134 знахідки всього (Critical: 1, High: 11, Medium: ~45, Low: ~50, Info: ~27)
- Зусилля на топ-9 critical/high: 4-6 годин в одного інженера
- Зусилля на цей спринт: 1-2 тижні
- Зусилля на цей квартал: ~4-5 тижнів cumulative

**Загальний висновок:** проект — суттєво вище середнього для одноосібного MVP. Структура коду, async-дисципліна, observability, інфра-як-код, preflight скрипти — усе свідчить про вдумливу інженерну культуру. Гострі болі — точкові: переважно "obviously good intentions, забули завершити" (CSP TODO, certbot Phase 2, Mypy strict-but-unenforced, ports !reset на alertmanager забули). Зробіть топ-9 цього тижня — і проект з "thoughtful MVP" переходить у "production-grade for what it is" при тих самих $0/міс.

---

*Звіт згенерований 4-ма паралельними агентами + автоматичні сканери: gitleaks 8.21.2, detect-secrets 1.5, pip-audit, pnpm audit, ruff 0.14, mypy 1.20, hadolint 2.12, yamllint, bandit. Raw JSON saved у `/tmp/{gitleaks,api-audit,bot-audit,scheduler-audit,ingest-audit,pnpm-audit,detect-secrets,bandit-*}.json` (sandbox, не persists).*
