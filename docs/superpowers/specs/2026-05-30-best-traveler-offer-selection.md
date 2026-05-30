# Spec: deal-selection honesty fixes

**Status:** approved 2026-05-30. Surgical deal-honesty changes.

## Problem

`apps/scheduler/src/jobs/detect_deals.py` collapses many candidate
offers for one hotel down to a single `deals` row with
`SELECT DISTINCT ON (cand.hotel_id) … ORDER BY cand.hotel_id,
cand.discount_pct DESC`. It keeps **merely the highest discount
percent**, which is not the same as the best offer for a traveler:

- An offer that is "−6% vs its own neighbouring dates" at 100 000 ₴ wins
  over an offer that is "−5% vs its own neighbouring dates" at 90 000 ₴,
  even though the traveler pays 10 000 ₴ more for the higher-discount one.
- The tie-break after `discount_pct` is undefined (`DISTINCT ON` with no
  further key), so equal-discount candidates resolve non-deterministically
  — the published deal can flip between runs.

The same `DISTINCT ON (hotel_id)` per-hotel collapse exists in the
`promo_discount` branch, but promo winner ordering is deliberately left
unchanged in this patch.

Separately, the #44 date-dip false-deal guard capped implausible discounts
at 50 %, but the sibling `promo_discount` path still accepted any positive
operator strike-through discount. A promo with an inflated anchor such as
100 000 ₴ crossed out against a 10 000 ₴ live price would become a public
`promo_discount` deal at -90 %.

Runtime check on 2026-05-30 showed the promo path is currently dormant in
local dev (`promo_offers` newest row was 2026-05-27, zero rows with
`red_price_uah > price_uah`), while live local `calendar_anomaly` rows were
fresh and within the existing 4-50 % band. The promo gap is still a latent
honesty bug once real strike-through promos resume.

## Change 1: Date-Dip Winner

Per-hotel selection orders by, in priority:

1. `price_uah ASC` — the cheapest real price the traveler pays.
2. `discount_pct DESC` — at equal price, the bigger dip vs its neighbours.
3. `check_in ASC` — at equal price + discount, the sooner trip.
4. Deterministic tie-breakers (`nights`, `meal_plan`, `operator_id`,
   `room_category`) so the published row is stable across runs.

Applied to the `_DATE_DIP_SQL` per-hotel `DISTINCT ON (cand.hotel_id)`
selection only.

**Why date_dip threshold safety is preserved:** every date-dip candidate already clears
`price_uah < trimmed_mean * 0.96` (i.e. discount > 4 %), which is the same
floor the channel (`MIN_BROADCAST_DISCOUNT_PCT = 4`) and personal alerts
(`MIN_ALERT_DISCOUNT_PCT = 4`) enforce. So swapping to the cheaper
qualifying offer can never push a hotel below the publication threshold.
It can still affect whether that hotel lands inside the later per-country
or global top-N caps, because those caps rank selected hotel representatives
by `discount_pct`. That is acceptable policy for this change: a hotel should
compete using the best traveler offer that represents it, not a pricier
offer with a slightly larger percent dip.

## Change 2: Promo Implausibility Cap (both surfaces)

A new shared constant `PROMO_MAX_DISCOUNT_PCT = 70` lives in
`apps/shared/deal_detection.py` and is applied wherever an operator
strike-through becomes user-facing, so the channel and the website draw
one honest line:

1. **Scheduler detector** (`_PROMO_DISCOUNT_SQL`): promo candidates must
   satisfy `cand.discount_pct <= PROMO_MAX_DISCOUNT_PCT`, so an inflated
   anchor never becomes a published `promo_discount` deal. Existing promo
   ordering stays highest-discount-first (date-dip's price-first ordering
   is *not* applied to promos — see Out of scope).
2. **`/api/promotions` feed** (`promo_service._row_to_out`): an implausible
   strike-through degrades to the existing `has_real_discount = False`,
   `discount_pct = 0.0` state — the tour still lists, but without a fake
   "−90 %" framing. No new UI state; reuses the no-strike-through path.
3. **`/api/promotions?min_discount_pct=...` SQL filter**: uses the same cap,
   so an inflated 90 % anchor cannot pass the SQL filter and then serialize
   as a demoted 0 % non-discount row.

The cap is deliberately more permissive than the 50 % date-dip cap because
real last-minute operator promos can be steeper than same-hotel neighboring
date dips. The intent is to reject inflated anchors, not ordinary promos.
`70` is a **default to confirm** — there is no real strike-through promo
data yet to calibrate against (the path is dormant in local dev).

### Out of scope (deliberately unchanged)

- Price-first per-hotel ordering for `_PROMO_DISCOUNT_SQL`. The promo detector
  has no 4 % discount floor gate, so leading with `price_uah` could choose a
  cheaper sub-4 % promo over a steeper one and drop the hotel below the
  broadcast floor. Promo ordering remains unchanged.
- The per-country `ROW_NUMBER() OVER (PARTITION BY country_iso2 …)` cap
  and the final `ORDER BY discount_pct DESC … LIMIT :max_per_run`. Those
  rank hotels against each other for channel diversity / top-N — a
  separate policy from which offer *represents* a hotel.
- All detection thresholds in `DATE_DIP_POLICY` (spread, discount cap,
  min saving, lookahead). No gate moves; the candidate set is identical,
  only the per-hotel winner changes.

## Acceptance

- New integration test seeds two valid date-dip candidates for one hotel
  where the lower-price candidate has the *lower* discount; the detector
  inserts the lower-price offer. Fails on the old ordering, passes on new.
- New integration tests seed promo strike-through candidates:
  a 90 % promo is rejected, and a 35 % promo is still inserted.
- New API unit tests on `promo_service`: a 90 % strike-through reports
  `has_real_discount = False` / `discount_pct = 0.0`; a 35 % one keeps its
  discount; `min_discount_pct` SQL filtering uses the same cap.
- All scheduler + API unit/integration tests stay green when run with the
  documented local env (`DATABASE_URL=…/fasttravel_test`,
  `REDIS_URL=redis://127.0.0.1:6379/15`): scheduler 283 passed, API 96
  passed. (Omitting `REDIS_URL` lets `test_health` / `test_refresh_rate_limit`
  fall back to the docker-internal `redis:6379` host and fail — env, not code.)
- `ruff --no-cache` and `mypy` clean across api / scheduler / shared.
