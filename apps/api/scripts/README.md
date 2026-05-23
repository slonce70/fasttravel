# API scripts

One-shot maintenance / bootstrap scripts that run *inside* the api container.
Not part of the runtime application; not imported by `src/`.

## seed_demo

Populates a freshly-migrated database with 50 realistic Turkish hotels, 3
operators, hotel-operator mappings and a window of price observations,
then refreshes the materialized views. The intent is to make
`/hotels/[slug]`, `/api/hotels/{slug}/calendar` and the search endpoints
render meaningful content before the real ingest pipeline (Week 3) exists.

The script is **idempotent**: it checks for a sentinel hotel slug
(`rixos-premium-belek-belek-tr`) and exits if it already exists. To re-seed,
drop and recreate the database (or just the relevant tables).

### Run

Prerequisite — schema must already be migrated:

```bash
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
```

Default mode (~315 k price observations, 7 days of history):

```bash
docker compose run --rm api python -m scripts.seed_demo
```

Full mode (~2.7 M price observations, 30 days of history):

```bash
docker compose run --rm api python -m scripts.seed_demo --full
```

> **Note on the invocation path.** Inside the container the source tree is
> mounted at `/app` with `PYTHONPATH=/app`. There is no `apps/api/` prefix
> inside the image, so the module path is `scripts.seed_demo` (not
> `apps.api.scripts.seed_demo`).

### What it writes

| Table                     | Rows (default)      | Rows (`--full`)       |
| ------------------------- | ------------------- | --------------------- |
| `operators`               | 3                   | 3                     |
| `destinations`            | 6 (country + 5 reg) | 6                     |
| `hotels`                  | 50                  | 50                    |
| `hotel_operator_mapping`  | ~125                | ~125                  |
| `price_observations`      | ~315 000            | ~2 700 000            |
| `current_prices` (MV)     | ~45 000             | ~45 000               |
| `hotel_calendar_prices`   | 3 000 (50 × 60 days) | 3 000                |
| `price_baselines`         | ~600                | ~600                  |

Exact numbers vary because each hotel maps to a randomised 2-3 operators
and operator pricing has a per-operator ±8 % offset.

### How prices are simulated

* Stars-based base price in USD (3★ ≈ 800–1500, 4★ ≈ 1500–2500, 5★ ≈ 2500–3500)
* Multiplier by nights: 7n=1.00, 10n=1.35, 14n=1.85
* Multiplier by meal plan: HB=1.00, AI=1.25
* Smooth seasonality (`cos`-wave) peaking around 1 August
* ±10 % per-observation noise
* 6 randomly-picked hotels have 1–3 "deal-candidate" days with -25..-40 % cut
* USD → UAH at a flat fx_rate_to_uah = 41.5

The deal-candidate days exist so a future `detect_deals` worker has obvious
anomalies to find — we do **not** insert into `deals` ourselves.

### After seeding

Pick any seeded slug and open it in the web UI. A guaranteed-present one is:

```
http://localhost:3000/hotels/rixos-premium-belek-belek-tr
```

Or via the API directly:

```
curl http://localhost:8000/api/hotels/rixos-premium-belek-belek-tr
```
