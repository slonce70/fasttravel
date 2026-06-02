# Cheapest Tours («Найдешевші тури») — design

**Date:** 2026-06-03 · **Status:** approved (owner) · separate from the anomaly deal-detector.

## Purpose
Surface genuinely **cheap upcoming tours** (absolute-cheap, not relative dips), so near-term / low-season
cheap dates that the anomaly detector intentionally ignores still get visibility. This is **"cheapest now",
not a discount** — no «−X%», no strike-through, clearly distinct from the deal channel.

## Owner decisions (locked)
- **Surfaces:** Telegram bot (command + menu), Web (page), Telegram channel (daily digest) — all three.
- **Organization:** **TOP-3 distinct hotels per country** (diverse across destinations, not the same cheap hotels).
- **Metric:** absolute **price per tour**, with a **min-stars ≥ 3** filter (no hostels / 1–2★).

## Approach (A — on-demand shared SQL, no new table)
One query builder shared by API + scheduler; web + bot read the API. `current_prices` is already an MV, so no
new table/migration. Always fresh, DRY, $0-friendly.

### Core query — `apps/shared/cheapest_tours.py`
`cheapest_tours_sql()` returns SQL over `current_prices` joined to `hotels`/`destinations`:
- Filters: `h.stars >= :min_stars` (default 3), country resolved (via destinations, incl. parent), `check_in`
  in **+3..+90 days**, **freshness gate reused** — `observed_at >= NOW() - INTERVAL '36 hours'` (same constant
  family as `DATE_DIP_POLICY.max_candidate_age_hours`, so prices are never stale).
- Per hotel: cheapest offer (MIN `price_uah`), carrying nights / meal_plan / check_in / room_category / deep_link.
- Per country: `ROW_NUMBER() OVER (PARTITION BY country_iso2 ORDER BY price_uah ASC, hotel_id)` → keep rank ≤
  `:per_country` (default 3), **distinct hotels** (one row per hotel).
- Output columns: country_iso2, country_name, hotel_id, hotel_slug, hotel_name, stars, review_score,
  review_count, check_in, nights, meal_plan, price_uah, deep_link, rank.
- Owner knobs (constants in the module): `PER_COUNTRY=3`, `MIN_STARS=3`, freshness `36h`, lookahead `+3..+90`.

### Surfaces (all read the one source)
1. **API** — `GET /api/cheapest-tours` (`apps/api/src/services/cheapest_tours_service.py` +
   `routers/cheapest_tours.py`), Pydantic schema `CheapestToursOut` (list grouped by country, or flat ranked
   list the clients group). Cache headers / short revalidate friendly.
2. **Web** — new page `apps/web/src/app/cheap/page.tsx` (server component): countries → 3 cheapest hotels each,
   reuse `HotelCard`/UI primitives, link to hotel pages; SEO metadata; add to nav (`Header`/`Footer`) + sitemap.
3. **Bot** — `/cheap` command + main-menu button «🔥 Найдешевші тури» (`apps/bot/src/handlers/` +
   `keyboards/main_menu.py`), fetched via `infra/api_client.py`; renders a digest grouped by country with deep
   links. Honest copy: «ціна від», never «знижка».
4. **Channel** — daily scheduler job `apps/scheduler/src/jobs/post_cheapest_digest.py` registered in
   `scheduler/src/main.py` (CronTrigger, 1×/day, e.g. 08:00 Kyiv), posts «💸 Найдешевші тури по напрямках»
   via `shared/publishers/broadcast.py`. **Distinct format** from anomaly deals — just prices, no discount.

## Honesty & governance
- Separate from the detector; labelled "cheapest available", never a discount, never struck-through.
- Reuses the freshness gate → prices shown are recently re-confirmed.
- No detection-core behavior is touched.

## Testing
- shared/API: top-3 per country, `stars>=3` enforced, freshness gate drops stale, distinct hotels per country,
  ordering by price.
- bot: render test (grouped by country, deep links, «ціна від» copy, no «знижка»).
- web: component/page render test (countries + cards).
- scheduler: digest job test (selects + formats; no real Telegram send).

## Out of scope (YAGNI)
"Below historical median", per-night metric, user budget filters, multi-post channel cadence — later.
