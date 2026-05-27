# `tools/explore/` — one-shot maintenance scripts

Standalone scripts that run outside the normal scheduler / API path.
Each one documents its own usage in the docstring.

## What lives here

| Script | Purpose |
|---|---|
| [`backfill_stars.py`](backfill_stars.py) | Repopulate `hotels.stars` from the cached `hotels.description_uk` JSON-LD when an older snapshot missed the field. Idempotent, safe to re-run. |

## What used to live here (deleted May 2026)

Eleven exploration / reverse-engineering scripts (`explore_*.py`,
`fetch_farvater_prices.py`, `find_booking_url.py`) were scratch files
used to discover the farvater.travel API surface back when
`snapshot_farvater.py` was being written. The findings are now baked
into the production job's docstring and into ADR notes; the scripts
themselves had become dead code (no app imports, no docs links).

## Running

```bash
# From inside the running scheduler container (preferred):
docker compose exec -T scheduler python -m tools.explore.backfill_stars

# Ad-hoc against a local clone (needs a venv with the scheduler deps):
cd apps/scheduler && poetry install --with dev
poetry run python ../../tools/explore/backfill_stars.py
```
