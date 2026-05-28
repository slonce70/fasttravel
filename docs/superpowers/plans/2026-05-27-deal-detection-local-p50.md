# Deal Detection Local P50 Plan

> **Status, 2026-05-28:** archived after implementation. Do not execute this as a live task list.

## Current Production State

- The scheduled detector runs two production strategies: `date_dip`, stored as
  `calendar_anomaly`, plus real operator strike-through promos stored as
  `promo_discount`.
- `date_dip` compares current prices inside the same hotel/operator/nights/meal/room-family-quality-view neighborhood and nearby check-in dates.
- `current_prices.room_family` is materialized and indexed so the detector can compare equivalent Farvater room labels without a slow per-row normalization scan, while keeping room quality tiers such as economy/standard/superior/deluxe separate.
- Public channel posting is limited to real, recent, non-peer deals that pass `MIN_BROADCAST_DISCOUNT_PCT`.
- `percentile` and `peer_anomaly` remain API/render-supported historical methods,
  but they are not active detector branches. Bucket-only promo flags remain in
  `/api/promotions`; only `red_price_uah > price_uah` promos become deals.
- `peer_anomaly` remains excluded from the public channel and has a stricter personal-alert threshold.
- Comparison baselines render as an "орієнтир"; strike-through and "економія" wording are reserved for real operator strike-through baselines.

## Verification Pointers

- Detector semantics: `apps/scheduler/tests/test_calendar_anomaly_semantics.py`
- SQL safety: `apps/scheduler/tests/test_deal_safety_sql.py`
- DB-backed selection contracts: `apps/scheduler/tests/integration/test_deal_selection_sql.py`
- Room-family MV/index migration: `apps/api/migrations/versions/021_current_prices_room_family.py`
- Render semantics: `apps/scheduler/tests/test_post_deals_render.py`, `apps/scheduler/tests/test_notify_subscribers.py`, `apps/bot/tests/test_templates.py`, `apps/web/src/components/DealCard.test.tsx`
