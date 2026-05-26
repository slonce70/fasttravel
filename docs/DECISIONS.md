# Architecture Decision Records (ADR)

Формат: коротко (1 параграф) — Context, Decision, Consequences.

---

## ADR-001: Backend = Python 3.12 + FastAPI

**Context.** Треба обрати мову для бекенду який буде робити багато HTTP-запитів (scraping + API ingestion), мати Telegram-бота, працювати з Postgres, і бути добре доступним для AI-агентів які пишуть код.

**Decision.** Python 3.12 + FastAPI 0.115 + uvicorn.

**Consequences.**
- ✅ Найкраща екосистема для scraping (`aiohttp`, `httpx`, `curl_cffi`, `playwright`)
- ✅ `aiogram 3` — найзріліша Telegram-бібліотека
- ✅ Type-safe API через Pydantic + OpenAPI з коробки
- ✅ AI-агенти добре пишуть Python (вище training data quality ніж Go/Rust)
- ⚠️ GIL — масштабуємо горизонтально через Celery/workers
- ❌ Менш швидкий runtime ніж Go, але для MVP це не bottleneck (Postgres = bottleneck)

**Альтернативи відкинуто:** Node.js (NestJS) — слабші scraping lib; Go — слабша екосистема для anti-bot і AI-агенти гірше пишуть.

---

## ADR-002: Frontend = Cloudflare Workers + OpenNext (НЕ Vercel)

**Context.** Хостинг для Next.js фронтенду. Стандартний вибір — Vercel.

**Decision.** Cloudflare Workers з `@opennextjs/cloudflare` adapter.

**Consequences.**
- ✅ Vercel Hobby plan TOS забороняє commercial use. FastTravel — affiliate-агрегатор, це commercial. Pro = $20/міс.
- ✅ Cloudflare Workers — без commercial-обмеження
- ✅ Unlimited bandwidth (Vercel Hobby обмежує 100GB/міс)
- ✅ Один vendor (DNS + CDN + WAF + Workers + R2) — простіше керувати
- ✅ OpenNext підтримує Next.js Node runtime на Cloudflare краще, ніж deprecated `@cloudflare/next-on-pages`
- ⚠️ Деякі Next.js features потребують Cloudflare-specific bindings (Image Optimization, cache persistence) — приймаємо як trade-off

**Альтернативи відкинуто:** Vercel Hobby (commercial заборона), Netlify (limited free build minutes), self-hosted (Oracle VM має зайнятись бекендом).

---

## ADR-003: DB = self-hosted Postgres 16 на Oracle (НЕ Supabase, НЕ Neon)

**Context.** Очікувані обсяги: ~12M рядків у hot 60-day window для `price_observations`, ~2.4 GB. Treba швидкий доступ для calendar UI і MV refresh.

**Decision.** Postgres 16 self-hosted у Docker на Oracle Cloud Always Free VM. Розширення: `pg_partman`, `pg_trgm`, `pg_cron`.

**Consequences.**
- ✅ Supabase free tier — лише 500MB DB. Наші 2.4GB не вмістяться. Pro = $25/міс.
- ✅ Neon free tier — 0.5 GB compute + scale-to-zero (1-3s cold-start), що ламає calendar UX
- ✅ Oracle VM має 24GB RAM + 200GB block storage — Postgres з належним налаштуванням покриває роки росту
- ✅ Self-hosted = повний контроль (розширення, partition strategy, vacuum tuning)
- ⚠️ Adopt operational overhead (backups, monitoring, restarts)
- ⚠️ Single point of failure — мітигується щоденним R2 backup і Terraform для швидкого rebuild

**Альтернативи відкинуто:** Supabase (замало), Neon (cold-start), PlanetScale (не вільний з 2024), Railway (free tier обмежений)

---

## ADR-004: Compute = Oracle Cloud Always Free (ARM Ampere)

**Context.** Потрібен сервер для бекенду + БД + бота + scheduler. Бюджет $0/міс на MVP.

**Decision.** Oracle Cloud Always Free Tier: VM.Standard.A1.Flex, 4 OCPU ARM Ampere + 24 GB RAM + 200 GB block + 2 Reserved Public IPs + 10TB egress, регіон Frankfurt.

**Consequences.**
- ✅ **Безкоштовно назавжди** (на відміну від AWS/GCP 12-місячних trials)
- ✅ Reserved Public IP вирішує IP-bind у ittour API (вони whitelist'ять конкретний IP)
- ✅ 24 GB RAM достатньо для Postgres + Redis + всі сервіси на одній VM
- ⚠️ Reclamation policy: якщо CPU<20% AND network<20% AND memory<20% протягом 7 днів — забирають. Cron-навантаження від snapshot_jobs тримає CPU >25%, тому не потрапляємо.
- ⚠️ ARM архітектура — деякі pip пакети без wheels (рідко у Python 3.12)
- ⚠️ Україна не підтримується для billing — реєстрація на Frankfurt/Amsterdam region
- ⚠️ Disaster recovery: усе як IaC у git, rebuild займає 30 хв

**Альтернативи відкинуто:** Hetzner CX22 (€4/міс — не $0), Fly.io free (deprecated 2024), Railway free (limited), DigitalOcean (немає free tier)

---

## ADR-005: Data source = IT-tour API (primary), farvater scrape (bootstrap)

**Context.** Українські туроператори (Anex, Coral, Join UP, ALF, TPG) не мають публічних REST API. Доступ через посередників-агрегаторів (ittour, otpusk) або підписані агентські договори (місяці бюрократії).

**Decision.** Primary track: ittour.com.ua API через партнерство. Bootstrap fallback (тільки якщо ittour мовчить >2 тижні): scraping farvater.travel.

**Consequences.**
- ✅ ittour — український SaaS на якому ймовірно працюють farvater і turne (підтверджено robots.txt сигнатурою `*/ws.asmx/`)
- ✅ JSON API задокументований публічно (api.ittour.com.ua)
- ✅ Базова версія "умовно безкоштовна" — оплата лише за advanced методи
- ⚠️ IP-bind — вимагає Reserved Public IP (є на Oracle Free)
- ⚠️ Bootstrap scraping farvater — публічні дані, не personal, юридично безпечно для UA, але operativно ризиковано (Cloudflare 403 на іншому конкуренті turne.ua вже є)
- ❌ НЕ використовуємо: Tourvisor, Sletat, Travelpayouts/Aviasales, RateHawk — все російського походження

**Альтернативи відкинуто:** прямі XML-договори з кожним оператором (6+ місяців бюрократії), RU-сервіси (виключені з причин репутації)

---

## ADR-006: Deal detection = percentile rule (НЕ ML на MVP)

**Context.** Виявляти "гарячі знижки" для Telegram broadcast.

**Decision.** SQL-trigger з правилом:
- `price < p15(60-day history)` для (hotel × nights × meal × month)
- AND `price < p50 * 0.85`
- AND `(p50 - price) >= 2000 UAH`
- AND check_in BETWEEN +5 AND +90 days
- AND `observation_count >= 10` (захист від малих вибірок)
- AND no other deal for this hotel in last 24h (cooldown)

**Consequences.**
- ✅ Працює БЕЗ архіву (Isolation Forest, Prophet вимагають 3+ місяці)
- ✅ Інтерпретовно ("дешевше за 85% спостережень")
- ✅ Robust до non-stationary даних (тури мають тренди + сезонність)
- ⚠️ Cold-start 14-30 днів — використовуємо fallback "ціна < 70% від середньої по destination × stars"
- 🔄 Phase 2 (за 3-6 міс) — додаємо Prophet baseline + Isolation Forest для outlier filtering

**Альтернативи відкинуто:** ML на MVP (немає архіву), Z-score (assumes normal distribution, тур-ціни right-skewed), Bollinger Bands (assume stationarity)

---

## ADR-007: Schedule = systemd timers + APScheduler (НЕ GitHub Actions cron)

**Context.** Потрібен надійний cron для 15-хвилинного refresh цін.

**Decision.** systemd timers на Oracle VM для жорсткого регламентного refresh (snapshot 2×/день). APScheduler всередині FastAPI/scheduler процесу для хвилинних джобів (refresh MVs, detect deals, post Telegram). GitHub Actions тільки для daily/weekly (бекап, sitemap).

**Consequences.**
- ✅ systemd — детерміновано, виконується точно в зазначений час
- ✅ APScheduler — простий API, dev-friendly, у тому ж процесі що FastAPI
- ❌ GitHub Actions cron — "best effort", затримки 15+ хв звичайні, скіпається під навантаженням. Не підходить для price refresh.
- ⚠️ Якщо Oracle VM рестартує — APScheduler перезапускає всі джоби (idempotent design обов'язковий)

---

## ADR-008: Telegram bot = aiogram 3 (НЕ Telegraf, НЕ pyrogram)

**Context.** Бібліотека для Telegram-бота.

**Decision.** aiogram 3.x (async, type-safe, MTProto через bot API).

**Consequences.**
- ✅ Async-native, добре інтегрується з FastAPI асинхроном
- ✅ Type-safe handlers через Pydantic-like моделі
- ✅ Вбудований FSM, middleware, throttling (`limited-aiogram` add-on для rate-limit)
- ❌ Telegraf — Node.js, у нас Python stack
- ❌ Pyrogram — MTProto-based, потужніше, але overkill для broadcast use case

---

## ADR-009: Storage backup = Cloudflare R2 (НЕ AWS S3, НЕ Backblaze)

**Context.** Місце для щоденних pg_dump бекапів.

**Decision.** Cloudflare R2 — 10GB storage free + 10M Class A ops free + **0 egress fees**.

**Consequences.**
- ✅ 0 egress — restore не коштуватиме нічого
- ✅ S3-compatible API
- ✅ Один vendor з Cloudflare DNS+Workers/R2
- ⚠️ 10GB free — наші щоденні pg_dump ~50MB × 30 днів rotation = 1.5 GB, влазимо
- ⚠️ Class B operations (PUT) платні з 1M req/міс — для щоденних upload не наближаємось

**Альтернативи відкинуто:** AWS S3 (egress $0.09/GB), Backblaze B2 ($0.005/GB-month + egress).

---

## ADR-010: pg_partman 5.x API (НЕ 4.x signature)

**Context.** Партиціонування `price_observations` по тижнях через `pg_partman`. Між версіями API різний.

**Decision.** Використовуємо `pg_partman` **5.4.3** з named arguments syntax: `partman.create_parent(p_parent_table := 'public.price_observations', p_control := 'observed_at', p_interval := '1 week', p_premake := 4)`.

**Consequences.**
- ✅ 5.x — поточна актуальна гілка з активною підтримкою
- ✅ Pinned через PGDG apt package `postgresql-16-partman=5.4.3` у `infra/postgres/Dockerfile`
- ⚠️ 4.x positional syntax `create_parent('parent', 'control', 'native', 'weekly')` НЕ ПРАЦЮЄ — впадете якщо знайдете старий tutorial
- ⚠️ При upgrade Postgres перевіряти compatibility matrix pg_partman

---

## ADR-011: Materialized views ініціалізуються `WITH NO DATA`

**Context.** Три materialized views (`current_prices`, `hotel_calendar_prices`, `price_baselines`) створюються у міграції `001_init`. Якщо створити з даними — `REFRESH ... CONCURRENTLY` буде непотрібно довго на порожній БД.

**Decision.** MVs створюються `WITH NO DATA`. Перший refresh — non-concurrent, ручний (документується у `apps/api/README.md` step 4). Подальші — CONCURRENTLY через cron.

**Consequences.**
- ✅ Швидкий первинний deploy (міграція мс, не сек)
- ✅ CONCURRENTLY refresh працює тільки якщо MV вже має дані — це fundamental Postgres constraint
- ⚠️ SELECT з не-приміреної MV кидає `ObjectNotInPrerequisiteStateError` → у README bootstrap step обов'язковий

---

## ADR-012: Endpoint contract — `/{slug}` для SEO, `/{id}` для performance

**Context.** Хочемо красиві SEO URL для індексації, але всередині API працювати з int ID швидше (індекси).

**Decision.**
- `GET /api/hotels/{slug}` — SEO entry point, повертає full hotel object включно з `id`
- `GET /api/hotels/{id}/calendar`, `GET /api/hotels/{id}/offers` — внутрішні, працюють з int id

**Consequences.**
- ✅ Frontend робить 1 slug-resolve, далі reuse id для подальших calls (TanStack Query cache)
- ✅ slug URL'и красиві: `/hotels/tt-hotels-pegasos-resort-kemer-tr` для SEO
- ✅ int id швидший на joins (4 bytes vs ~50 для slug)
- ⚠️ Якщо slug змінюється — потрібен 301 redirect (Phase 2)

---

## ADR-013: Poetry (НЕ pip-tools, НЕ uv) для Python dep management

**Context.** Управління Python залежностями.

**Decision.** Poetry 1.8+ з `pyproject.toml` + `poetry.lock`.

**Consequences.**
- ✅ Cleaner Docker export path (`poetry export -f requirements.txt`)
- ✅ Stricter lockfile ніж pip-tools
- ✅ Dep-groups: `[tool.poetry.dependencies]`, `[tool.poetry.group.dev]`, `[tool.poetry.group.test]` — окремо для prod/dev/test
- ⚠️ uv (Astral) швидший і модніший, але lock format ще нестабільний у 2026. Перейдемо коли стабілізується.
- ⚠️ pip-tools — простіший, але без dep-groups і повільніший resolver

---

## ADR-014: НЕ авто-мігрувати при старті контейнера

**Context.** Деякі стеки роблять `alembic upgrade head` у entrypoint Docker-контейнера API. Це може призвести до schema drift, race condition при кількох інстансах, та незмогою rollback.

**Decision.** Migrations — це **one-shot** операція, виконується **окремою командою** перед стартом сервісів: `docker compose run --rm api alembic upgrade head`.

**Consequences.**
- ✅ Deploy сценарій явний і контрольований
- ✅ Multiple API replicas не б'ються на одну міграцію
- ✅ Rollback легко: `alembic downgrade -1`
- ⚠️ Розробник має пам'ятати про крок міграції (документуємо у README і CI/CD workflow)
- ⚠️ Прямий `docker compose up -d` БЕЗ міграції видасть `relation does not exist` помилки — fail-loud, fail-fast

---

## ADR-015: Tailwind CSS 3.x (НЕ 4.x на MVP)

**Context.** План передбачав Tailwind 4, але v4 використовує CSS-first config (`@theme` directive, `@tailwindcss/postcss`), що несумісно з нашою setup з `tailwind.config.ts` + `postcss.config.js`.

**Decision.** Pin `tailwindcss@^3.4.14`. Міграція на v4 — у Phase 2 після стабілізації design-system.

**Consequences.**
- ✅ Стабільний stack, мільйони прикладів і компонент-бібліотек
- ✅ TypeScript config file (`tailwind.config.ts`) — type-safe customization
- ⚠️ v4 швидший і має кращу DX, але CSS-first config вимагає переписати всю конфігурацію
- ⚠️ Коли мігруємо — перевірити що `react-day-picker` стилі сумісні з v4 layer system

---

## ADR-016: react-day-picker v9 з `DayButton` override (НЕ DayContent)

**Context.** План згадував `DayContent` для кастомного рендерингу комірки календаря. react-day-picker v9 видалив цей API.

**Decision.** Використовуємо `components.DayButton` override для рендерингу price + heatmap background + 🔥 індикатор у `PriceCalendar.tsx`.

**Consequences.**
- ✅ v9 — поточна актуальна версія з активною підтримкою
- ✅ `DayButton` дає повний контроль над button element (рекомендований підхід v9)
- ⚠️ Tutorials з v8 (з `DayContent`) не працюють — звертатись до офіційних v9 docs
- ⚠️ При upgrade перевіряти migration guide

---

## ADR-017: OpenNext cache persistence через Cloudflare R2

**Context.** Next.js `revalidate` / ISR у Cloudflare Workers потребує persistent cache binding, якщо хочемо стабільну поведінку між Worker instances.

**Decision.** MVP deploy іде через `@opennextjs/cloudflare` без примусового R2 cache binding. Коли production account готовий, додаємо R2 binding для OpenNext incremental cache і перевіряємо `pnpm cf:build && pnpm cf:preview`.

**Consequences.**
- ✅ Немає фейкового "cache configured" без реального Cloudflare account/bucket.
- ✅ OpenNext має documented R2 path для cache persistence.
- ⚠️ До R2 binding частина revalidate/ISR виграшу може бути слабшою; це прийнятно для MVP і має бути перевірено після cutover.

---

## ADR-018: Local-first development, VPS deploy відкладено

**Context.** Початково передбачав Oracle Cloud signup на Day 1. Користувач уточнив що зробить VPS пізніше — поки розробляємо локально.

**Decision.** Day 1-2 пріоритет — повний робочий стек на `docker compose up -d` на локальній машині розробника. Production VPS — Phase 2 (Week 6+), коли продукт буде готовий до beta-launch.

**Consequences.**
- ✅ Швидше unblocking — користувач може тестувати UI ще цього тижня без external dependencies
- ✅ Інфра-як-код (Terraform + cloud-init) залишається у `infra/` як ready-to-use артефакт
- ⚠️ ittour API IP-bind — обходимо через bootstrap scraping farvater (з локального IP) для перших тижнів тестів; коли буде VPS — переключаємось на ittour direct
- ⚠️ Telegram broadcast буде через локальний bot інстанс на час розробки — підходить для тестового приватного каналу, не для production-канала
