# Deal Detector Redesign — analysis & recommendation (for owner sign-off)

_Read-only analysis workflow (7 agents) over the live primed DB (~613k current_prices). 2026-06-02._

## The finding

The current date-dip detector is systematically publishing **seasonal price-step artifacts, not real deals**. On live data the new logic rejects **3323 of 3404 (97.6%)** of the current detector's per-hotel-best rows. Genuine isolated dips are rare in the data (the population census finds ~358 true two-sided 'V' dips across ~45k series).

### Data shape census
SERIES-SHAPE CENSUS (population scan over ~45,252 (hotel,operator,nights,meal,room_family) series, check_in CURRENT_DATE..+120, per-date MIN price; all via pure SQL WINDOW functions on current_prices). The dominant shape is a LOW-SEASON PLATEAU -> HIGH-SEASON RAMP/STEP: a flat run that steps or ramps up into peak season. The candidate the current detector flags is almost always the FLOOR of the cheap plateau (or the last day before a data gap/step), i.e. AT its own regime level, NOT below it. This is the Ugur bug, and it is systemic, not a one-off: the published 'deals' table is 100% calendar_anomaly and the top of it is dominated by ~40-50% 'discounts' clustered on shared boundary dates (e.g. 2026-07-17, 2026-08-26, 2026-07-01 recur across many different Montenegro/Turkey hotels = a seasonal step boundary, not independent deals). Flat-then-ramp and step/spike windows vastly outnumber genuine isolated dips.

QUANTIFIED RARITY OF GENUINE DIPS (the recall guard). Counts of the SAME candidate population under progressively stricter, all-SQL-window tests: (1) naive 'below both immediate neighbors with tight shoulders' = 12,669; (2) 'is the +-7d window minimum' = 90,304; (3) the discriminating two-sided test [split +-7d-PRECEDING and +-7d-FOLLOWING frames, >=3 neighbors each side, candidate < each side's MIN*0.95, AND the two side-AVERAGES match within 10% (return-to-baseline, not a step), depth <=25%] = only 358. So clean isolated V-dips are ~0.8% of series; the +-7d window minimum is ~25x more common and is mostly plateau floors. GENUINE DIPS DO EXIST (358) but are RARE -- the redesign must be a precise V-detector, not a 'cheapest nearby date' detector.

CRITICAL MECHANISM FINDING (premise-relevant). Of the 358 V-dips, 239 have candidate-date nrows=1 (a single underlying price row = a SAME-ROOM temporal dip: the room's own price dropped one day; e.g. Kalim, Kleopatra) and 119 have nrows>=2. Inspecting the nrows>=2 ones revealed the 'dip' is frequently a CROSS-ROOM-CATEGORY COLLAPSE: on the dip date a cheaper room_category appears within the same room_family and lowers the family MIN, while the 'normal' rooms do not dip. Often the two rows are CASING DUPLICATES of one room ('Deluxe Room' vs 'DELUXE ROOM', 'Standard Room' vs 'STANDARD ROOM') -- two catalog rows for what is really one room, with one carrying a lower price. These are REAL bookable prices (deep_link present) and (checked) FRESH (Rehana's cheap+normal rows observed_at within ~1 day of each other), so they are genuine cheaper offers -- but the 'dip' is an artifact of family-min collapsing heterogeneous labels, NOT a same-room price cut. This is an OWNER decision the redesign surfaces: do we treat a cheaper concurrently-bookable sub-room as a deal? The truest recall cases are the nrows=1 same-room dips. Every genuine_dip/borderline case in this set states its mechanism in label_rationale because the family-MIN series alone HIDES this (an evaluator reading only the series sees a clean V and would mislabel).

ISOLATED DEEP CLIFFS ARE A SEPARATE, NON-DEAL CLASS. There also exist single-day ~40-60% drops in SPARSE/volatile series (e.g. Castellastva 44644 between two ~90k days, 16-day gaps). These are NOT genuine dips -- per product intent real dips are MODEST (~5-25%) -- and are the signature of stale/child/glitch single rows. The current detector publishes them at the top (49.88%). The redesign should regime-localize the baseline AND cap implausibly deep single-row drops; do NOT count these toward recall.

IMPLICATIONS FOR THE REDESIGN (anchored to the two required cases). A regime-LOCAL, TWO-SIDED baseline implemented as two separate +-7d window frames (PRECEDING-only and FOLLOWING-only, which exclude self automatically -- avoids the nested-window and LATERAL-blowup problems) cleanly: REJECTS Ugur 11-Jun (candidate AT its cheap-regime floor ~46799, the FOLLOWING shoulder is the peak step so the 'below both sides' test fails) and FLAGS the genuine $900->$800 shape (Jiraporn/Kalim: below both matched shoulders, prices return). Two design levers must be OWNER decisions (data provided to set them): (a) the DIP THRESHOLD (5-12% borderline band populated: ReefOasis 5.7%, Parrotel 6.2%, SideYesiloz 6.6%, SeaBeach ~8%, Himeros 8.4%); (b) the SHOULDER DEFINITION -- comparing the candidate to the local MIN vs the local MEAN flips several borderline cases by a few points (Parrotel ~6% vs ~8%), so this choice is itself part of the operating point. A max-depth cap (~25-30%) is also needed to exclude glitch cliffs without discarding real dips like Rehana (~26%, but corroborated and fresh).

## Recommended algorithm — two-sided regime-local V-detector
PRIMARY (recommended): a two-sided regime-local V-detector implemented as pure SQL window functions over current_prices. For each (hotel, operator, nights, meal_plan, room_family) series of per-date family MINs, compute two RANGE-interval frames over +-7 calendar days: a PRECEDING-only frame (7d..1d before) and a FOLLOWING-only frame (1d..7d after), each yielding side MIN, side AVG and side COUNT. A candidate date is a deal only when ALL hold: (1) prec_n>=3 AND foll_n>=3 (gap-awareness, self-exclusion is automatic); (2) price < prec_min AND price < foll_min (strict two-sided V-bottom: below the cheapest neighbouring date on BOTH sides); (3) the two side AVGs match within a SIDE_MATCH_RATIO of 1.15 (return-to-baseline, not a seasonal step); (4) discount-vs-baseline >= DIP_THRESHOLD_PCT and <= MAX_DEPTH_PCT (35) and absolute saving >= 1500 UAH. The displayed baseline_p50 = the matched-side AVERAGE round((prec_avg+foll_avg)/2) (the honest 'typical local price for these dates'); discount_pct is computed vs that average. KEY SPLIT: the shape gate fires on the side MIN (precise V-bottom) but the baseline shown/measured-against is the side AVG (so the on-card 'у середньому' / average is literally true). On the 18-case labeled set this gives recall 6/6 on genuine dips, 5/5 rejection of seasonal artifacts, and both flat controls reject. There is no FALLBACK detector needed; the single design subsumes the strengths of the rejected candidates (median robustness to spikes, modal's regime-locality) without their failure modes (Mercure narrow-low-island, modal noisy-flat blindness).

FALLBACK / degrade-gracefully lever rather than a second detector: if the owner wants higher recall at the cost of precision, relax condition (2) from side MIN to side AVG (candidate below the local typical level rather than below the cheapest neighbour) — this raises the pool from ~342 to ~6365 at 5%. Recommend keeping the MIN-shoulder shape gate (the precise V) as primary.

### Why (rationale)
The root cause is regime-mixing: any fixed-window central-tendency estimator (trimmed mean, KNN median, mode) over a +-14/21/10d window is wrong when the window spans two price regimes, because it has no concept of which regime the candidate belongs to. Confirmed on live data: Ugur 14 AI 06-11 (46746) sits at its own early-June floor (~46799 to the left) but the OLD detector's PERCENT_RANK trim collapsed the eight identical 46799 neighbours to rank 0, trimmed them OUT, and averaged the mid/late-June peak cluster (77897) -> false 40% (spread 1.7896 squeaked under the 1.8 guard).

The two-sided V-test fixes this WITHOUT a global spread veto (which the advisor forbade because it discards real dips when a window legitimately contains both a dip and a later step). It is NON-CIRCULAR: regimes are defined TEMPORALLY (the +-7d preceding and following frames), never by price-similarity to the candidate. Each artifact is rejected by a DIFFERENT, principled mechanism (redundancy is a feature):
- Ugur: side_ratio 1.664 >> 1.15 (the two sides are different regimes -> not a return-to-baseline dip); also foll_n only counts 2 peak dates. Note: measured vs side-AVG Ugur shows 25% 'discount', so magnitude ALONE would not reject it — the shape/side-ratio gates are what discriminate.
- Mercure: side_ratio 1.313 (preceding ~280k vs following ~211k don't match — it's a step). Magnitude can't separate it (24.9% < genuine Rehana 27%).
- Obala Ponta / Aleksandar: foll_n=1 (spike window — gap-aware rejects).
- Castellastva: prec_n=1 (16-day gaps starve the preceding side) AND 45-50% > depth cap.

The genuine $900->$800 product-intent shape (Jiraporn/Kalim/Veligandu/Kleopatra/Kiroseiz/Rehana) all flag at 12-27% with side_ratio <= 1.025 (clean V, sides match). Left-edge dips (Jiraporn/Kalim at check_in = today+5) survive because the series CTE is built from the FULL MV (CURRENT_DATE..+90d), not the +5d candidate floor — the +5..+90 filter is applied only as candidate eligibility. Performance: pure window functions, ~1.8s over 613k rows (the LATERAL+PERCENTILE_CONT forms the other candidates used TIMED OUT on the population; PERCENTILE_CONT cannot be a window function at all — hence MIN/AVG over RANGE frames).

### Parameters (owner-governed knobs, pre-set with anchor-justified margins)
DIP_THRESHOLD_PCT = 8 (owner knob; 5 honors 'even ~5%' intent, 10-12 for pronounced-only; 12 is the recall floor). SHOULDER_FRAME = +-7 calendar days (RANGE 7d PRECEDING..1d PRECEDING and 1d FOLLOWING..7d FOLLOWING). MIN_NEIGHBORS_PER_SIDE = 3 (gap-awareness). SHOULDER_DEFINITION = MIN (precise V-bottom; AVG is the higher-recall alternative). SIDE_MATCH_RATIO = 1.15 (return-to-baseline; genuine anchors <=1.025, artifacts >=1.31). MAX_DEPTH_PCT = 35 (glitch-cliff cap; Rehana 27% safe with margin). MIN_ABSOLUTE_SAVING_UAH = 1500 (unchanged). DISPLAYED baseline_p50 = matched-side AVERAGE round((prec_avg+foll_avg)/2). All seven are owner-governed (detection-core governance) and are pre-set with anchor-justified margins — present as owner-confirmable, not autonomous edits.

## Owner threshold decision
RECOMMENDED operating point = MIN-shoulder shape gate + discount measured vs matched-side AVERAGE (baseline_p50), abs floor 1500 UAH, depth cap 35%, side_ratio 1.15. Candidate-pool counts (the pipeline then DISTINCT ON (hotel_id) + country_cap 5 + LIMIT 50 publishes only the top 50/run):

| dip_pct | pool/run | distinct hotels | published artifact rate (top-30 by disc, eyeballed) |
|---------|----------|-----------------|------------------------------------------------------|
| 5%      | ~2346    | ~889            | ~7% (2/30 casing-dup collapse; ~20/30 single-row same-room dips; ~8/30 multi-room) |
| 8%      | ~1356    | ~660            | similar; deep band 24-34% unchanged (LIMIT 50 publishes the deep end first) |
| 10%     | ~897     | ~500            | similar |
| 12%     | ~582     | ~370            | similar; recall floor — Kiroseiz (~12%) drops at 13% |

Contrast with the OLD detector: ~62,516 candidate rows, top-50 published 100% seasonal-step artifacts clustered at the 49% cap. The new published deep band (24-34%) is dominated by genuine single-row same-room temporal dips, NOT glitch cliffs.

SHOULDER-DEFINITION lever (governed, flips ~2pp on borderlines): MIN-shoulder (recommended, ~342 pool @5%, matches the census's discriminating bucket-3 of 358) vs AVG-shoulder (~6365 pool @5%, higher recall/lower precision). Anchor flips: ReefOasis 5.7% (MIN) vs 8.4% (AVG-mid); Parrotel 6.2% vs 8.9%.

**Recommendation:** Recommend dip_pct = 8% with the MIN-shoulder shape gate. Rationale: at 8% the pool is ~1356 (the pipeline publishes 50/run regardless of pool size, so the threshold mainly governs which dips are ELIGIBLE, not volume); 8% sits above the borderline band (ReefOasis 5.7%, Parrotel 6.2%, SideYesiloz 6.6%) so the channel surfaces clearly-felt savings while still keeping recall 6/6 on the genuine-dip anchors (shallowest genuine = Kiroseiz ~12%, well clear). 5% is a defensible alternative if the owner wants to surface the shallow borderline dips (product intent explicitly says 'EVEN ~5%'); 10-12% if the owner wants only pronounced dips. The depth cap 35%, side_ratio 1.15, abs floor 1500, and shoulder=MIN are the other FOUR governed knobs and are pre-set with anchor-justified margins (see below) — present them as owner-confirmable, not autonomous.

### Options
- dip_pct = 5% (honors 'even ~5%' product intent; surfaces shallow borderline dips ReefOasis/Parrotel/SideYesiloz; pool ~2346)
- dip_pct = 8% (RECOMMENDED; above the borderline band, recall 6/6 intact, pool ~1356)
- dip_pct = 10% or 12% (only pronounced dips; pool ~897 / ~582; at 13% loses Kiroseiz so 12% is the recall floor)
- shoulder = MIN (RECOMMENDED, precise V-bottom, pool ~342@5%) vs shoulder = AVG (higher recall, pool ~6365@5%, lower precision)
- depth cap 35% (RECOMMENDED, Rehana 27% safe with margin; removes only 9 deep glitch-cliffs) vs tighter cap ~30% if cross-room collapses are excluded by the dedup decision (then deepest TRUE dip ~19-20%)
- side_ratio 1.15 (RECOMMENDED; genuine anchors <=1.025, Volga 1.119 worst real; artifacts Mercure 1.313 / Madifushi 1.356 / Ugur 1.664 — clean separation gap) vs 1.10 (stricter, may drop noisy-regime real dips)

## Before / after diff on real data (the governance artifact)
METHODOLOGY: the deals table does NOT store room_family, so published rows cannot be re-evaluated by a simple join; instead the OLD detector was reproduced as a read-only SELECT (the inner pipeline, INSERT stripped) over current_prices, and the NEW logic recomputed over the same keys. 'Before' = OLD candidate set; the OLD pipeline's DISTINCT ON (hotel_id) gives 3404 per-hotel-best rows (of which the pipeline publishes only ~50/run by discount DESC).\n\nREJECTED BY NEW: of the 3404 OLD per-hotel-best rows, NEW logic rejects 3323 (97.6%) and keeps 81. The OLD published deals are almost entirely seasonal-step artifacts. ~5 examples (ALL are actual 6/02-published rows except Ugur, which is a live OLD candidate at 39.99% that was buried below the LIMIT):\n- Ugur Hotel Beach 14 AI 06-11, OLD 46746 vs baseline 77897 = 40% -> REJECT: candidate is at its own cheap floor (side_ratio 1.664, sides are different regimes; disc-vs-local-floor 0.1%).\n- Castellastva 7 HB 08-26, OLD 44644 vs 89067 = 49.88% -> REJECT: prec_n=1 (16-day gap starves preceding side) AND 45% > 35% depth cap (glitch cliff).\n- La Mer / Aquarius / Aleksandar budva / Slovenska Plaza / Obala Zelena (all 7 HB 08-26, OLD ~49%) -> REJECT: prec_n=1 — the recurring 08-26 seasonal-step boundary, isolated points after a data gap.\n- Agape / Hotel Polar Star (7 BB 07-01, OLD ~48%) -> REJECT: prec_n=0 (first row of a regime after the 07-01 step boundary).\n- Madifushi Private Island 11 BB 06-26, OLD 45.8% -> REJECT: side_ratio 1.356 (sides don't match — a step, not a dip; NEW disc only 13.6%).\n\nNEW LOCAL-DIPS FLAGGED: 378 total NEW flags. CRUCIAL framing: only 22 are net-new candidate keys; the other 356 were ALREADY in the OLD pool but BURIED below the 49% artifacts by ORDER BY discount_pct DESC LIMIT 50 — so the recall win is UN-BURYING genuine dips via ranking, not 378 brand-new dips. ~5 examples with numbers (side_ratio ~1.0 = clean return-to-baseline):\n- Veligandu Island Resort 9 BB 06-27: 212409 vs local ~251765 = 15.6% (flat run, one day below; textbook V).\n- Kleopatra Fatih 7 AI 07-18: 40614 vs ~48843 = 16.8% (tight plateau).\n- Xperience Kiroseiz 8 AI 07-14: 84910 vs ~96494 = 12.0% (July plateau, ignores the earlier 06-23 ramp).\n- Ght Oasis Park & Spa 7 BB 06-16 (NET-NEW, not in OLD pool): 47775 vs ~68679 = 30.4% (OLD's +-14d window straddled a >1.8x step -> spread guard killed it).\n- Bliss Nada Beach 7 AI 06-13 (NET-NEW): 46882 vs ~65467 = 28.4%.\n\nFlat controls (Altea, Maria Palace) correctly stay un-flagged (0.0-0.1%). Anchor recall 6/6, artifact rejection 5/5.

## Render / card copy changes
CONTEXT (apps/shared/deal_rendering.py render_deal_price_semantics, date_anomaly branch lines 76-86): the card currently shows headline '📉 На {discount}% дешевше за сусідні дати в цьому готелі', price_line '💰 {price} · у середньому ~{baseline}~' (strikethrough), gated by savings = max(0, baseline_int - price_int) > 0.\n\nWHAT CHANGES — almost nothing in code, and the strikethrough becomes HONEST:\n1. baseline_p50 now = the matched-side AVERAGE (round((prec_avg+foll_avg)/2)) = the genuine typical local price for the surrounding dates. So 'у середньому ~{baseline}~' ('on average') is now LITERALLY TRUE — it really is the average of the neighbouring dates' levels, computed only within the candidate's own regime (the side_ratio<=1.15 gate guarantees both sides are one regime). The original lie (showing a peak-season trimmed mean as 'average') is structurally closed. No wording change is strictly required; «у середньому» can stand.\n2. The headline percentage auto-tracks: discount_pct = 100*(1 - price/baseline_p50) is derived from the new baseline, so the headline % self-corrects with no render change (Ugur would now never reach the card; if it somehow did it would read ~0%, suppressed by the savings>0 gate).\n3. The savings = max(0, baseline - price) gate auto-suppresses the strikethrough when baseline correctly sits near price (the desired behavior for non-dips). Trust this gate to receive the new baseline.\n\nOWNER-FACING OPTION (governed copy — flag, do not silently change): if the owner prefers the wording to name the estimator more precisely, replace «у середньому» with «звичайна ціна на ці дати» ('the usual price for these dates') or «зазвичай ~{baseline}~». This is a wording preference, NOT a correctness fix — both are now accurate. Recommend keeping «у середньому» (shortest, now true) unless the owner wants the 'usual local price' framing. NOTE: if the owner instead keeps the shape gate but displays the side MIN as baseline, the copy MUST change to 'дешевше за найдешевшу сусідню дату' (not 'average') — but that is the weaker value prop and is not the recommendation.

## Duplicate-rows items (separate)
TWO distinct duplicate issues; lead with the deals-table cross-run dups (the likely intent), and address the casing-dup separately.\n\n(1) DEALS-TABLE CROSS-RUN DUPLICATES (orthogonal to detection — address separately). The deals natural-key unique constraint (uq_deals_natural_key_day) includes (detected_at AT TIME ZONE 'UTC')::date, so the SAME (hotel_id, check_in, nights, meal_plan, detection_method) re-published on different days creates a NEW row each day. Live count: 3893 total rows across 6 detection days collapse to 2725 distinct natural keys -> 1168 duplicate rows. This is a storage/idempotency artifact, NOT a detection bug; the redesign does not change it. If the owner wants one row per deal across reruns, address via the natural-key constraint (drop the detection-date component) or an upsert that refreshes detected_at — a separate, low-risk migration item.\n\n(2) CASING-DUPLICATE ROOM ROWS (detection-relevant; surfaces in the published deep band). Within one (hotel, nights, meal, room_family, check_in), the catalog can carry two rows for the SAME room differing only by casing ('Deluxe Room' 79793 vs 'DELUXE ROOM' 108285 — confirmed for Rehana 11 UAI deluxe:any 07-14). The family MIN then collapses to the cheaper label, manufacturing a ~26-27% 'dip' that is a labeling artifact (or a genuine cheaper concurrent sub-room — an OWNER decision the redesign surfaces). In the recommended logic's published top-30 by discount, 2/30 are casing-dup collapses (both Rehana hotels), ~8/30 are genuinely-different concurrent rooms, ~20/30 are single-row same-room temporal dips (the highest-confidence class). This couples to the depth-cap decision: if the owner treats cross-room casing collapses as NON-deals, the deepest TRUE genuine dip falls to ~19-20% (Jiraporn-class) and the 35% cap can tighten. Optional mitigation: dedup current_prices on (room_family, check_in, lower(trim(room_category))) before taking the family MIN, or require the dip date's cheapest room_category to also appear (and be the min) on at least one shoulder date.

## Risks
1. RECALL — short-regime / horizon edges. (a) Candidates at +84..+90d have foll_n<3 (the MV ends at CURRENT_DATE+90) and are silently dropped — symmetric to the left-edge buffer that the full-series CTE fixes for +5d candidates; minor recall loss at the far horizon. (b) Series with <3 priced dates within +-7d on either side (sparse/gappy operators) are dropped — by design (gap-awareness), but real dips in genuinely sparse series are missed.\n2. RECALL — flat-bottom dips. Strict price < prec_min AND price < foll_min rejects 2-adjacent-equal-low dips (the second low day's preceding MIN equals it, so it is not STRICTLY below -> disc 0). All 6 anchor dips are single-day V's (6/6 holds), but real 2-day-bottom dips are a known FN class. Relaxing to <= admits them but also admits flat-slope edges; leave strict unless the owner sees misses.\n3. RECALL — side_ratio 1.15 rejects genuine dips on steep MONOTONIC ramps (no return-to-baseline because the price keeps climbing). This is intentional (a dip on a ramp is hard to distinguish from a step) but it is a recall tradeoff; the constant is the 4th governed knob.\n4. SELECTION still ranks discount DESC and publishes the deepest 50 first (the spec's 'selection amplifies worst artifacts' mode). After the shape gate this mostly surfaces genuine DEEP dips (Rehana-class) ahead of modest 5-8% ones; the published deep band is now ~93% genuine (vs 0% for OLD), but if the owner wants modest local dips surfaced, the ORDER BY may warrant revisiting (selection is governed — flag, do not change).\n5. DEPTH-CAP COUPLING to the dedup decision (see dedup_note): the 35% cap is justified by Rehana 27% (which is itself a casing-dup collapse). The cap is load-bearing-but-minimal — it removes only 9 deep glitch-cliffs (single-row ~40-52% drops clustered on shared boundary dates like 07-22). Rehana is safe at any cap > 27%.\n6. MV COST. The detector reads current_prices twice (the series GROUP BY + the per-row cheapest-room LATERAL). Verified ~1.8s over 613k rows — acceptable, far cheaper than the OLD per-row LATERAL (~4.8s). The cheapest-room LATERAL could be folded into the series CTE (carry an argmin) if cost matters; not needed now.\n7. room_family mis-bucketing (migration 021) is unchanged and can still merge/split room tiers, contaminating the neighbour set — a pre-existing data-quality risk the redesign does not address.\n\nALTERNATIVES CONSIDERED & REJECTED: (a) KNN-by-date median — non-robust when the candidate's regime is short (Mercure 2-date low island -> median lands on peak; 4 deep tunable-proof FPs). (b) Short rolling median + LAG/LEAD local-min — the census's NAIVE bucket-1 detector (~11k flags/run); still flags Mercure (median lands on peak when the cheap regime is >7d away) and lacks return-to-baseline. (c) Modal adjacent level — still a fixed-window central-tendency estimator (flags Mercure when a gap pushes the regime outside +-10d) AND abstains on noisy-flat regimes (blocks ReefOasis) -> anti-useful as a gate. (d) Tighten the global spread guard — forbidden: kills windows that legitimately contain both a dip and a later step, discarding real dips.

## Recommended SQL block
```sql
-- Slot-in replacement for the `priced` + `local_stats` CTEs in
-- apps/scheduler/src/jobs/detect_deals.py (_DATE_DIP_SQL). Full block + the
-- required inner-SELECT change saved at /tmp/RECOMMENDED_detect_deals_block.sql.
-- Verified end-to-end against the live primed DB (composes through DISTINCT ON ->
-- country_rank -> LIMIT 50; emits baseline_p50/discount_pct/room_category/deep_link).

WITH series AS (
    -- Per-date family MIN over the FULL MV (incl. the <+5d left shoulder so
    -- early-window candidates still have a preceding frame; MV floor is CURRENT_DATE).
    SELECT cp.hotel_id, cp.operator_id, cp.nights, cp.meal_plan, cp.room_family,
           cp.check_in, MIN(cp.price_uah) AS price_uah
    FROM current_prices cp
    WHERE cp.check_in BETWEEN CURRENT_DATE - INTERVAL '7 days'
                         AND CURRENT_DATE + INTERVAL '90 days'
    GROUP BY cp.hotel_id, cp.operator_id, cp.nights, cp.meal_plan, cp.room_family, cp.check_in
),
framed AS (
    SELECT s.*,
        MIN(s.price_uah) OVER w_prec AS prec_min,
        AVG(s.price_uah) OVER w_prec AS prec_avg,
        COUNT(*)         OVER w_prec AS prec_n,
        MIN(s.price_uah) OVER w_foll AS foll_min,
        AVG(s.price_uah) OVER w_foll AS foll_avg,
        COUNT(*)         OVER w_foll AS foll_n
    FROM series s
    WINDOW
        w_prec AS (PARTITION BY s.hotel_id, s.operator_id, s.nights, s.meal_plan, s.room_family
                   ORDER BY s.check_in
                   RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 day' PRECEDING),
        w_foll AS (PARTITION BY s.hotel_id, s.operator_id, s.nights, s.meal_plan, s.room_family
                   ORDER BY s.check_in
                   RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND INTERVAL '7 days' FOLLOWING)
),
local_stats AS (
    SELECT f.hotel_id, f.operator_id, f.check_in, f.nights, f.meal_plan, f.room_family,
        f.price_uah,
        cheapest.room_category,             -- room_category + deep_link of the actual
        cheapest.deep_link,                 -- cheapest underlying row on the dip date
        ROUND((f.prec_avg + f.foll_avg) / 2)::int AS baseline_p50,   -- matched-side AVERAGE
        ROUND(100 * (1 - f.price_uah::numeric / ((f.prec_avg + f.foll_avg) / 2)), 2) AS discount_pct
    FROM framed f
    JOIN LATERAL (
        SELECT cp.room_category, cp.deep_link FROM current_prices cp
        WHERE cp.hotel_id=f.hotel_id AND cp.operator_id=f.operator_id AND cp.nights=f.nights
          AND cp.meal_plan=f.meal_plan AND cp.room_family=f.room_family AND cp.check_in=f.check_in
        ORDER BY cp.price_uah ASC LIMIT 1
    ) cheapest ON TRUE
    WHERE f.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days' AND CURRENT_DATE + INTERVAL '90 days'
      AND f.prec_n >= 3 AND f.foll_n >= 3                      -- gap-aware: >=3 dates each side
      AND f.price_uah < f.prec_min AND f.price_uah < f.foll_min  -- two-sided V-bottom
      AND GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) * 1.15  -- return-to-baseline
)
-- MODIFIED inner SELECT (was detect_deals.py lines 122-140): trimmed_mean is gone,
-- so read baseline_p50/discount_pct straight through and swap the magnitude WHERE.
-- Everything below `cand` (DISTINCT ON (hotel_id) ... country_rank ... LIMIT) is UNCHANGED.
--   FROM (
--     SELECT cp.hotel_id, cp.operator_id, cp.check_in, cp.nights, cp.meal_plan,
--            cp.room_category, cp.price_uah, cp.baseline_p50, cp.discount_pct,
--            cp.deep_link, dest.country_iso2 AS country_iso2
--     FROM local_stats cp
--     JOIN hotels h ON h.id = cp.hotel_id
--     LEFT JOIN destinations dest ON dest.id = h.destination_id
--     WHERE cp.discount_pct >= :DIP_THRESHOLD_PCT   -- owner knob (5/8/10/12)
--       AND cp.discount_pct <= 35                   -- MAX_DEPTH_PCT
--       AND (cp.baseline_p50 - cp.price_uah) >= 1500 -- abs floor
--   ) cand
```


---

## Implementation outcome (2026-06-02)

**Shipped** (owner-approved: threshold 8%, MIN-shoulder, + all three extras):
- `apps/shared/deal_detection.py` — new `DateDipPolicy` + shared `date_dip_local_v_cte_sql()` (regime-local two-sided V; same-room casing MAX-collapse).
- `apps/scheduler/src/jobs/detect_deals.py` — channel detector uses the shared CTE; gates discount∈[8,35] & saving≥1500; promo branch unchanged.
- `apps/api/src/services/calendar_service.py` — the web calendar's per-day "cheap date" marker uses the SAME CTE, so site + channel agree.
- `apps/shared/deal_rendering.py` — bot card copy «у середньому» → «звичайна ціна» (now literally true).
- `apps/api/migrations/versions/023_deals_dedup_drop_detection_day.py` — dedup `deals` (re-points the notification ledger first; drops the per-day natural-key component).

**Verified:** ruff/format clean; mypy api=0/scheduler=0/bot=0; scheduler unit 287; bot 108; API 100; scheduler integration 10 (all on a clean DB); migration 023 applies clean. Live anchors on the real 600k-row data: Ugur 2026-06-11 **rejected** (side_ratio 1.664); Ght Oasis 2026-06-16 (32.3%) + Bliss Nada 2026-06-13 (28.4%) **kept**. Adversarial review: no blockers.

**Known recall tradeoff (owner-flag, NOT a bug):** the strict two-sided `<` means two genuine dips within ±7d of each other mutually cancel (each sees the other at-or-below on one side) — so a recurring weekly-cadence dip can be suppressed (~658 candidate-rows on live data, but the top-50 / per-hotel / 5-per-country selector means far fewer lost posts). It only ever *rejects*, never fabricates a false deal. Relaxing to `<=` with a strict-min-over-both-frames tie-break would recover these — a detection-behavior change for owner sign-off if weekly-cadence dips matter.

**Test-coverage note:** each guard is locked by an isolated synthetic test (the seasonal-step test, not the over-determined Ugur case, is the true side-ratio lock). Live-hotel anchors are verified manually, not pinned in CI (a data-dependent anchor test would be flaky as the catalog refreshes).
