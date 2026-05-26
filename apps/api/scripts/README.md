# Scripts

Synthetic seed scripts from the old demo-data path were
removed on 2026-05-23. They produced picsum.photos images and template
descriptions that the audit user flagged as fake. All real catalog +
prices now come from `apps/scheduler/src/jobs/snapshot_catalog_farvater.py`
and `snapshot_farvater.py`.

`seed_e2e.py` is the only exception: it seeds a tiny, namespaced
`ci-e2e-*` fixture into an ephemeral GitHub Actions database so Playwright can
exercise the real API + DB + frontend flow before deploy. It is not part of
local demo content or production bootstrap. The script refuses to seed unless
`FASTTRAVEL_ALLOW_E2E_SEED=1` is set and `ENVIRONMENT` is not `prod`; use
`python -m scripts.seed_e2e --cleanup` to remove accidental local fixture rows.

`check_deal_sanity.py` is a read-only runtime gate for the Farvater deal
pipeline. It exits non-zero if public deals contain `discount_pct <= 0` or
if unposted legacy `bucket_%` deals are still queued for Telegram.

Re-introducing a seed should:
1. Mark synthetic hotels with `is_synthetic=TRUE` (new column) so the
   search/deal layer can filter them out by default.
2. Use ittour or TBO content URLs, not picsum.
