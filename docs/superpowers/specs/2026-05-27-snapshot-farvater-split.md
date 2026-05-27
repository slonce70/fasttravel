# Spec: Split snapshot_farvater.py into focused modules

**Status:** deferred from the May 2026 audit-closure sprint (single
session — too risky to do alongside everything else). Carry into the
next maintenance window.

## Why

`apps/scheduler/src/jobs/snapshot_farvater.py` is 1284 LOC mixing six
responsibilities (see audit 1.2 Medium):

1. **HTTP catalog walker** — `_list_country_hotels`,
   `_list_sitemap_hotels`, page fetch via `FarvaterProdClient`.
2. **HTML/JSON-LD extractors** — `_name_from_url_path`,
   `_extract_hotel_name`, `_extract_gallery`, `_parse_jsonld`,
   `_review_from_jsonld`, `_extract_stars`, etc.
3. **Hotel upsert** — `_upsert_hotel` + `_upsert_mapping` +
   `_ensure_operator` + `_country_dest_id`.
4. **Price validation insert** — `_insert_prices` + `_dedup_existing`
   + `_decay_active_prices`.
5. **Materialised-view refresh + freshness metric** —
   `_record_run` + `_mark_priced`.
6. **Job entrypoint + concurrency control** — `snapshot_farvater()`
   + `_process_hotel` + `_refresh_targets` + `_http_client()`.

The mix means: a regex tweak risks breaking the SQL path; the
concurrency knobs are buried at the bottom; tests have to import the
whole module to exercise any one piece.

## Target structure

```
apps/scheduler/src/
├── clients/
│   ├── __init__.py
│   ├── farvater_catalog.py        # NEW — pure HTTP walker (1-2)
│   └── (existing static_tours.py)
├── services/
│   ├── __init__.py
│   ├── hotel_upsert.py            # NEW — _upsert_hotel + _upsert_mapping (3)
│   ├── price_insert.py            # NEW — _insert_prices + _dedup_existing (4)
│   └── snapshot_telemetry.py      # NEW — _record_run + _mark_priced (5)
└── jobs/
    └── snapshot_farvater.py       # SHRUNK — orchestration only (6)
```

## Migration steps

Do these as separate commits so each can be reverted independently:

1. **Lift extractors into `clients/farvater_catalog.py`** —
   move `_name_from_url_path`, `_extract_hotel_name`,
   `_extract_gallery`, `_parse_jsonld`, `_review_from_jsonld`,
   `_extract_stars`, `_looks_like_farvater_boilerplate`,
   `_clean_description`, `_clean_title`. These are pure functions
   with no DB / no HTTP — easiest to test in isolation.

2. **Lift the HTTP walkers** —
   `_list_country_hotels`, `_list_sitemap_hotels`,
   `_fetch_hotel_meta`, `_fetch_calendar`, `_http_client`,
   `_make_slug`. Keeps client-side concerns together.

3. **Lift hotel upsert** —
   `_ensure_operator`, `_country_dest_id`, `_upsert_hotel`,
   `_upsert_mapping`. Add unit tests against the real PG service
   the new scheduler CI block provides (audit Sprint #12).

4. **Lift price-insert + dedup** —
   `_insert_prices`, `_dedup_existing`, `_decay_active_prices`,
   `_mark_priced`. These compose with `_upsert_hotel` so move next.

5. **Lift telemetry** — `_record_run` + freshness metric.

6. **Shrink the job** — `snapshot_farvater()` + `_process_hotel` +
   `_refresh_targets` import from the new modules. Final file
   ~150-200 LOC of orchestration.

## Acceptance

- `find apps/scheduler/src/jobs/snapshot_farvater.py -printf '%s'`
  drops from ~50 KB to < 10 KB.
- All existing scheduler tests still pass (`pytest tests/`).
- New unit tests cover extractors with cassettes (no live HTTP).
- New integration tests cover hotel_upsert + price_insert against
  the CI Postgres service.

## Estimate

3-4 days for one engineer, including code review. The work is
mechanical but every step needs `pytest tests/` to stay green —
the regex extractors are the highest-risk part because they were
tuned against live farvater pages and we don't have a golden
fixture corpus.
