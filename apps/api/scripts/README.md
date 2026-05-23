# Scripts

Synthetic-seed scripts (`seed_demo.py`, `seed_multicountry.py`) were
removed on 2026-05-23. They produced picsum.photos images and template
descriptions that the audit user flagged as fake. All real catalog +
prices now come from `apps/scheduler/src/jobs/snapshot_catalog_farvater.py`
and `snapshot_farvater.py`.

Re-introducing a seed should:
1. Mark synthetic hotels with `is_synthetic=TRUE` (new column) so the
   search/deal layer can filter them out by default.
2. Use ittour or TBO content URLs, not picsum.
