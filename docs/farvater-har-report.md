# Farvater HAR Investigation Report

**Date:** 2026-05-25
**Author:** automated HAR probe (curl_cffi, chrome120 impersonation)
**Purpose:** Identify which `farvater.travel` endpoints carry operator-flagged
promotion signals (`isPromo` / `isHot` / `redPriceUAH` / `actionPrice` /
`oldPriceUAH` / etc.), so the FastTravel snapshot pipeline can capture and
surface them.

---

## TL;DR (critical answer for snapshot_farvater)

**`POST /uk/tour/stat/low-price-calendar/auto`** (the endpoint
`apps/scheduler/src/jobs/snapshot_farvater.py` currently calls) returns price
calendars **only** — it has NO `isHot`, `isPromo`, `isEarly`, `redPriceUAH`,
`isRecommended`, `isOtp`, `operatorName`, or any other promo / operator flag.
Its per-row schema is just `{night, dates:[{date, price, priceUAH, day, meal,
room, systemKey}]}`. Promo flags **cannot** be inferred from this endpoint.

**The correct source of operator-flagged promotion signals is
`POST /uk/catalog/static-tours`** (the AJAX endpoint that hydrates
`/uk/gorjashhie-tury_*`, `/uk/rannee-bronirovanie_*`, etc.). It is documented
nowhere but is referenced inside the public bundle
`/Scripts/V4SEOcatalog?build=5001.70`. It returns a `tourPackage.tours[]` array
where every row carries `isHot`, `isPromo`, `isEarly`, `isBestDeal`,
`isRecommended`, `IsChoiceFarvater`, `isOtp`, `isLastSeats`, `IsBlackFriday`,
`isVip`, `HotType`, `EarlyType`, `RecommendedType`, `priceUAH`, `redPriceUAH`,
`operatorName`, `operatorIdInt`, `LoadedDate`, `promotionEndDate`, `SystemKey`,
`hotelKey`, etc.

**Recommended pipeline change:** add a second, much cheaper ingest job that
sweeps `/uk/catalog/static-tours` once per `slugTypes` bucket
(`gorjashhie-tury`, `rannee-bronirovanie`, `akcionnye-tury`) per country
several times per day; persist `(hotelKey, SystemKey, isHot, isEarly, isPromo,
isOtp, IsChoiceFarvater, priceUAH, redPriceUAH, operatorName, promotionEndDate,
LoadedDate)` and join into the price-calendar snapshot by `hotelKey`.

**Important nomenclature surprise:** `isPromo` and `isAction` / `actionPrice` /
`oldPriceUAH` (named in the original task brief) **do not exist** on farvater
as live signals. The closest real flags are `isHot`, `isEarly`,
`IsChoiceFarvater`, `isOtp`. `redPriceUAH` exists but in the current snapshot
it equals `priceUAH` in 50/50 returned hot tours — it is NOT a struck-through
"was X now Y" field.

---

## Sample Set

### "Hot" hotels (extracted from `/uk/gorjashhie-tury_tury-v-stranu-turtsiya/`)

Note: this catalog URL is the "Turkey hot tours" SEO page, but its SSR HTML
contains only **placeholder skeleton cards** (every flag `false`, every price
`0`). The real listing is hydrated client-side via `/uk/catalog/static-tours`.
The 9 hotel slugs picked from the SSR page therefore are NOT necessarily
"hot" — they are just hotels whose card link happened to render. We verified
this by cross-referencing: **0/9 picked slugs appeared in the live
`static-tours` hot-tour response.**

| hotelKey | slug | category | url |
|----------|------|----------|-----|
| 45689 | tt-hotels-pegasos-resort | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/tt-hotels-pegasos-resort/ |
| 46438 | oz-hotels-antalya-hotel | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/oz-hotels-antalya-hotel/ |
| 67410 | marcan-beach-hotel | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/marcan-beach-hotel/ |
| 167776 | otium-hotel-life | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/otium-hotel-life/ |
| 226198 | hotel-novano | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/hotel-novano/ |
| 227696 | eightdays-hotel-istanbul | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/eightdays-hotel-istanbul/ |
| 336302 | acapulco-beach-spa-resort | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/acapulco-beach-spa-resort/ |
| 356524 | days-hotel-by-wyndham-istanbul-maltepe | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/days-hotel-by-wyndham-istanbul-maltepe/ |
| 455393 | vox-maris-resort | hot (skeleton sample) | https://farvater.travel/uk/hotel/tr/vox-maris-resort/ |

(Only 9 hot hotel URLs were extracted from the page — the SSR pattern shows
50 cards but most of those have `hotelUrl` paths under `/hotel/` rather than
`/uk/hotel/`. The Turkey-prefixed regex matched 9.)

### Baseline (sitemap-hotelpages-3.xml)

**Not collected.** The candidate URL
`https://farvater.travel/sitemap-hotelpages-3.xml` returns HTTP 404 (139 KB
HTML 404 page). The root `sitemap.xml` lists different submaps; the
hotelpages-N tier no longer exists in the May 2026 sitemap. The "baseline
non-hot" comparison set therefore could not be probed via that route.

This turned out to be **moot** for the investigation: once we discovered that
`/uk/catalog/static-tours` returns a `tourPackage.tours[]` array with explicit
per-row promo flags, the per-hotel "hot vs baseline" comparison was not
needed. The flags are carried on the *tour row*, not on the hotel entity, and
the catalog endpoint returns BOTH hot and non-hot tours depending on
`slugTypes`.

### Live "hot" sample from `/uk/catalog/static-tours` (filterModel
`{slugTypes:["gorjashhie-tury"], countryId:-1, pageSize:50}`)

50 live tours (10 shown):

| hotelKey | hotel | country | isHot | isRec | isOtp | priceUAH | redPriceUAH | operatorName |
|----------|-------|---------|-------|-------|-------|----------|-------------|--------------|
| 15937 | Arena Beach | Мальдіви | True | True | True | 29847 | 29847 | Alliance |
| 41708 | Ioli Village Hotel | Греція | True | False | True | 36140 | 36140 | Aristeya |
| 70125 | Vavien Hotel | Туреччина | True | True | True | 40484 | 40484 | Alf Ua |
| 366962 | Evilion Hotel | Греція | True | False | True | 47761 | 47761 | (various) |
| 41284 | STELLA BEACH | Греція | True | False | True | 49681 | 49681 | (various) |
| 175362 | Seven Days Hotel Istambul | Туреччина | True | False | True | 53594 | 53594 | (various) |
| 45160 | Venus Bıeno Hotel | Туреччина | True | True | True | 59148 | 59148 | (various) |
| 52880 | Kahlua Hotel and Suites | Греція | True | True | True | 59261 | 59261 | (various) |
| 356743 | Golden Bay Boutique Hotel & Bu... | Греція | True | True | True | 59994 | 59994 | (various) |
| 40853 | Marilisa Apartments | Греція | True | False | True | 60203 | 60203 | (various) |

Country distribution among 50 hot results: Туреччина=23, Греція=13, ОАЕ=9,
Іспанія=3, Мальдіви=1, Єгипет=1.
`tourPackage.totalItems = 635, minPrice = 29847, maxPrice = 82975`.

---

## Endpoints Probed

| HTTP | URL pattern | sCode dance? | Cloudflare? | avg resp size | JSON? | Notes |
|------|-------------|--------------|-------------|---------------|-------|-------|
| GET | `/uk/gorjashhie-tury_tury-v-stranu-turtsiya/` | no | none (chrome120 impersonation enough) | 331 KB | HTML | SSR with **placeholder skeleton** cards, all flags false, real data hydrated client-side |
| GET | `/uk/hotel/{iso2}/{slug}/` | no | none | ~250 KB | HTML | Contains `var TModel = {…}` block but flags / prices are all `false` / `0` — template, not data |
| POST | `/uk/tour/stat/low-price-calendar/auto?hotelKey=…&adults=…&meals=all&checkIn=DD.MM.YYYY` | no | none | 200 B – 5 KB | JSON | **No promo flags**. Only price calendar per night length |
| POST | `/tours/getminprice/?genId={hotelKey}` | no | none | 2.8 KB | HTML(500) | **Endpoint dead** — returns "500 Технические работы" HTML page for every hotel probed (9/9) |
| GET | `/sitemap-hotelpages-{1,2,3}.xml` | no | none | 139 KB (404) | HTML | All three return HTTP 404; tier no longer exists |
| GET | `/sitemap.xml` | no | none | 2.2 KB | XML | Sitemap index — exists but does not contain hotelpages-N |
| POST | `/uk/catalog/static-tours` | no | none | 94 KB | JSON | **Canonical promo-flag carrier**. Per-tour `isHot/isEarly/isOtp/isRecommended/IsChoiceFarvater/priceUAH/redPriceUAH/operatorName/LoadedDate/SystemKey/promotionEndDate/hotelKey` |
| POST | `/uk/catalog/static-tophotels` | no | none | not probed | JSON | Referenced in `/Scripts/V4SEOcatalog`; same companion endpoint; supplies `topHotels` array — flagged for follow-up but not required for hot-tours pipeline |
| POST | `/uk/catalog/static-statistic` | no | none | not probed | JSON | Filter badge counts — not relevant for promo capture |
| POST | `/api/searchstart2/` | unknown — skipped | unknown | — | — | Skipped per task budget; the SEO-catalog page never calls it (it uses `static-tours`) |

`/uk/catalog/static-tours` request payload (verbatim, what V4SEOcatalog.js
sends) — see "Schema Snapshots" below.

---

## Field Coverage Matrix — `/uk/catalog/static-tours`

50 live hot tours (`slugTypes=["gorjashhie-tury"]`, countryId=-1, adults=2,
pageSize=50, checkinList 2026-05-25 → 2026-06-17). All counts are
**true / total**.

### Boolean signal flags (per `tourPackage.tours[i]`)

| Field | true count | true rate | distinct values |
|-------|-----------:|----------:|-----------------|
| `isHot` | 50/50 | 100 % | {True} |
| `isPromo` | 0/50 | 0 % | {False} |
| `isVip` | 0/50 | 0 % | {False} |
| `isBestDeal` | 0/50 | 0 % | {False} |
| `isEarly` | 0/50 | 0 % | {False} |
| `isRecommended` | 26/50 | 52 % | {True, False} |
| `IsChoiceFarvater` | 2/50 | 4 % | {True, False} |
| `isOtp` | 23/50 | 46 % | {True, False} |
| `isLastSeats` | 1/50 | 2 % | {True, False} |
| `IsBlackFriday` | 0/50 | 0 % | {False} |
| `tourFreeCancel` | 0/50 | 0 % | {False} |
| `disablePromoCode` | 0/50 | 0 % | {False} |

### Integer "type" enums

| Field | non-zero count | distinct |
|-------|----------------|----------|
| `HotType` | 50/50 | [1] |
| `EarlyType` | 50/50 | [1] |
| `RecommendedType` | 50/50 | [1] |

These are constant `1` across the hot-tour bucket — appears to be a category
echo of the queried slugType rather than a per-row signal.

### Price fields

| Field | non-zero | sample values |
|-------|----------|---------------|
| `price` | 50/50 | 664, 691, 772, 931, 949, 1022 (in tour currency, mostly USD) |
| `priceUAH` | 50/50 | 29847, 36140, 40484, 47761, 49681, 53594 |
| `redPriceUAH` | 50/50 | 29847, 36140, 40484, 47761, 49681, 53594 |
| `customPriceWd` | 0/50 | (always 0 in this bucket) |
| `customPriceWdUah` | 0/50 | (always 0 in this bucket) |

**`redPriceUAH` == `priceUAH` in 50/50 tours.** In the current snapshot
`redPriceUAH` is NOT a struck-through "was-X-now-Y" old price. It is most
likely a display-side alias for the live red-highlighted UAH price. Treat
them as equivalent until a sample emerges where they differ.

### Operator / metadata

| Field | non-default | sample values |
|-------|-------------|---------------|
| `promotionEndDate` | 0/50 | (all null) |
| `operatorName` | 50/50 | "Alliance", "Aristeya", "Alf Ua", … |
| `LoadedDate` | 50/50 | "2026-05-24T22:56:42.853+03:00", … |

`promotionEndDate` is null across this sample, but the slot exists in the
schema — likely populated for `slugTypes=["akcionnye-tury"]` rows in other
seasons.

### Cross-bucket comparison

| slugTypes | totalItems | returned | isHot | isPromo | isEarly | isRecommended | isOtp | IsChoiceFarvater |
|-----------|-----------:|---------:|------:|--------:|--------:|--------------:|------:|-----------------:|
| `["gorjashhie-tury"]` | 635 | 50 | 50 | 0 | 0 | 26 | 23 | 2 |
| `["rannee-bronirovanie"]` | 1668 | 49 | 0 | 0 | 49 | 0 | 6 | 1 |
| `["akcionnye-tury"]` | 50 | 50 | 0 | 0 | 0 | 0 | 0 | 1 |
| `[]` (no slug filter) | 50 | 50 | 0 | 0 | 0 | 0 | 0 | 1 |

Reading this matrix:
- **`isHot` is the operator-flag for "hot tour".** Returned `true` iff the
  query asked for `gorjashhie-tury`. The catalog endpoint mirrors back what
  the slugType asked for.
- **`isEarly` is the operator-flag for "early booking".** Returned `true` iff
  the query asked for `rannee-bronirovanie`.
- **`isPromo` is never returned `true` anywhere.** It appears to be a legacy
  field that farvater no longer populates. Do not rely on it.
- **`akcionnye-tury` ("promo tours")** does not set `isPromo`, does not set
  any other flag; it just changes which 50 tours come back. The "promo-ness"
  is encoded by the fact that the tour appears in that bucket, not by a
  per-row boolean.
- `isRecommended`, `isOtp`, `IsChoiceFarvater`, `isLastSeats` are
  **orthogonal cross-cutting signals** — they can be true regardless of
  bucket, and so they ARE real per-row flags worth capturing.

### Fields named in the task brief that **do not exist** in any response

| Field name | Found anywhere? |
|------------|-----------------|
| `actionPrice` | **No** — not in `static-tours`, `low-price-calendar/auto`, hotel-page HTML, or any JS bundle |
| `oldPriceUAH` | **No** |
| `isAction` | **No** |
| `oldPrice` / `originalPrice` / `discountPercent` / `promoCode` | **No** |

These names appear to have been speculative when the task was authored. The
real promo signal set on the current 2026-05 farvater backend is the one
enumerated above.

---

## Field Coverage Matrix — `/uk/tour/stat/low-price-calendar/auto`

Probed for 10 hotels. For 9/10 the response was `data.items = []` (date range
01.07.2026 with dateShift 7 fell outside operator data). For the 10th
(`hotelKey=15937`, Arena Beach, verified isHot=true via static-tours) the
endpoint returned 3 night-buckets with date entries.

**Every field path in the calendar response:**

```
data
data.currency.{code, name, symbol}          # always {"EUR","Євро","€"} in sample
data.dateShift
data.hasMore
data.hash                                    # always []
data.hotel                                   # always "/hotel/{iso2}/{slug}"
data.items[]
data.items[].item.night                      # 7, 10, 14
data.items[].item.dates[].date               # "18.06.2026"
data.items[].item.dates[].day                # "Чт"
data.items[].item.dates[].meal               # "BB"
data.items[].item.dates[].price              # in EUR
data.items[].item.dates[].priceUAH
data.items[].item.dates[].room
data.items[].item.dates[].systemKey
data.minDate
data.syncType
statusCode
```

**Zero promo flag fields.** No `isHot`, no `isPromo`, no `isEarly`, no
`redPriceUAH`, no `operatorName`, no `IsChoiceFarvater`. The calendar gives
you (date × night × room × meal → price). Nothing else.

---

## Hotel Page TModel — Coverage Matrix

For all 9 probed hotel pages the inline `var TModel = {…}` block contains the
flag *fields*, but always with placeholder values:

| hotel | isHot | isPromo | isEarly | isBestDeal | isRecommended | IsChoiceFarvater | redPriceUAH | priceUAH |
|-------|-------|---------|---------|------------|---------------|------------------|-------------|----------|
| tt-hotels-pegasos-resort | false | false | false | false | false | false | 0 | 0 |
| oz-hotels-antalya-hotel | false | false | false | false | false | false | 0 | 0 |
| marcan-beach-hotel | false | false | false | false | false | false | 0 | 0 |
| otium-hotel-life | false | false | false | false | false | false | 0 | 0 |
| hotel-novano | false | false | false | false | false | false | 0 | 0 |
| eightdays-hotel-istanbul | false | false | false | false | false | false | 0 | 0 |
| acapulco-beach-spa-resort | false | false | false | false | false | false | 0 | 0 |
| days-hotel-by-wyndham-istanbul-maltepe | false | false | false | false | false | false | 0 | 0 |
| vox-maris-resort | false | false | false | false | false | false | 0 | 0 |
| **rate** | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 0 / 50000+ UAH | 0 |

`actionPrice`, `oldPriceUAH`, `isAction` are absent (no match in any HTML —
shown as `-` in the analyzer output).

Conclusion: TModel is a server-side template skeleton, hydrated browser-side
by the same `/uk/catalog/static-tours` call. Scraping the hotel page alone
gives you no promo signal.

---

## Promotion Signal Verdict (per candidate field)

| Field | Carried by `low-price-calendar/auto`? | Carried by `static-tours`? | Carried by hotel page TModel? | Stability across 50 hot samples | Recommendation |
|-------|---------------------------------------|----------------------------|-------------------------------|---------------------------------|----------------|
| `isHot` | **No** | **Yes** | placeholder only | 100 % when queried with `slugTypes=["gorjashhie-tury"]` | **Use `static-tours`** with `slugTypes=["gorjashhie-tury"]` to sweep the universe of hot tours |
| `isEarly` | No | **Yes** | placeholder only | 100 % when queried with `slugTypes=["rannee-bronirovanie"]` | Use `static-tours` with `slugTypes=["rannee-bronirovanie"]` |
| `isPromo` | No | field exists but never `true` | placeholder | 0 % | **Skip — field appears unused on the live backend.** Confirm before relying. |
| `isBestDeal` | No | field exists but never `true` in our 200-tour sample | placeholder | 0 % | Skip; same as above. |
| `isVip` | No | field exists but never `true` | absent | 0 % | Skip. |
| `isRecommended` | No | **Yes** | placeholder | 52 % of hot tours | Useful per-row signal — capture. |
| `IsChoiceFarvater` | No | **Yes** (rare) | placeholder | 2 – 4 % across buckets | Niche but real — capture. |
| `isOtp` | No | **Yes** | absent | 46 % of hot tours | Capture (semantic unclear — see Anomalies). |
| `isLastSeats` | No | **Yes** (rare) | absent | 2 % of hot tours | Capture. |
| `IsBlackFriday` | No | field exists but never `true` (off-season) | absent | 0 % | Capture schema; expect non-zero only in late-Nov. |
| `redPriceUAH` | No | **Yes** | placeholder | 100 % non-zero in hot tours; equals `priceUAH` in 50/50 | Capture but treat as alias of `priceUAH` until proven otherwise. |
| `priceUAH` | calendar has it (per-date) | tour-level | placeholder | 100 % non-zero in hot tours | Already captured via calendar. |
| `actionPrice` | No | **does not exist** | absent | — | **Field does not exist on farvater.** Remove from spec. |
| `oldPriceUAH` | No | **does not exist** | absent | — | **Field does not exist on farvater.** Remove from spec. |
| `isAction` | No | **does not exist** | absent | — | **Field does not exist on farvater.** Remove from spec. |
| `operatorName` | No | **Yes** | absent | 100 % | Capture — already a known gap in calendar-only ingest. |
| `LoadedDate` | No | **Yes** | absent | 100 % | Capture — gives data freshness per tour, vital for staleness checks. |
| `promotionEndDate` | No | **Yes** (slot exists; null in current sample) | absent | 0 % in our sample | Capture schema; may populate for `akcionnye-tury` bucket in other seasons. |
| `SystemKey` | calendar has it (per date row) | tour-level (e.g. `2p4191025733778095065c51`) | absent | 100 % | Already known; this is the operator deeplink key. |

---

## CRITICAL ANSWER for snapshot_farvater rewrite

> **Does `POST /tour/stat/low-price-calendar/auto` (which snapshot_farvater
> currently calls) return promo flags, or do we need to ALSO call another
> endpoint to capture them?**

**Answer: it does NOT return promo flags. We must ALSO call
`POST /uk/catalog/static-tours` to capture them.**

Evidence:
- The full set of fields returned by `low-price-calendar/auto` is enumerated
  above; none of `isHot`, `isPromo`, `isEarly`, `isRecommended`,
  `IsChoiceFarvater`, `isOtp`, `redPriceUAH`, `operatorName`, `LoadedDate`,
  or `promotionEndDate` appears.
- Confirmed against the live response for `hotelKey=15937` (Arena Beach,
  Maldives) — a hotel known to be flagged `isHot=true` by `static-tours`.
  Even for that hotel, its calendar response carries only `night, dates[].
  {date, price, priceUAH, day, meal, room, systemKey}`. The fact that this
  hotel is "hot" is invisible to a calendar-only ingest.
- Cross-confirmed by reading
  `apps/scheduler/src/jobs/snapshot_farvater.py` — current code uses only
  `low-price-calendar/auto` and the docstring lists only `/uk/hotel/{slug}/`
  and `/uk/tour/stat/low-price-calendar/auto`. No promo capture path exists.

### Recommended secondary fetch strategy

Add a new lightweight ingest job (e.g.
`apps/scheduler/src/jobs/snapshot_farvater_promo.py`) that, per refresh
window:

1. For each bucket in `["gorjashhie-tury", "rannee-bronirovanie",
   "akcionnye-tury"]`, and for each country of interest (or `countryId=-1`
   first), POST to `https://farvater.travel/uk/catalog/static-tours` with the
   payload below. Paginate via `pageIndex` until `pageIndex*pageSize >=
   totalItems` (e.g. 635 / 50 = 13 pages for hot Turkey).
2. For each returned tour row, persist:
   - `hotelKey` (the JOIN key into the price-calendar snapshot)
   - `SystemKey` (operator deeplink)
   - `slugType` bucket the tour came from (= the synthetic source of
     `isHot` / `isEarly` semantics)
   - All boolean flags: `isHot, isEarly, isRecommended, IsChoiceFarvater,
     isOtp, isLastSeats, IsBlackFriday, isPromo, isBestDeal, isVip,
     tourFreeCancel, disablePromoCode`
   - Numeric: `HotType, EarlyType, RecommendedType, price, priceUAH,
     redPriceUAH, currencyIdInt, operatorIdInt, FarTourId, rate`
   - Strings: `operatorName, currency, promotionEndDate, LoadedDate,
     cityFromName, cityFromCode, countryName, address`
   - Nested: `checkIn.value, region.RegionName, region.ResortName,
     hotel.value, star.value, meal.value`
   - Plus `hotelSpecialLinx[hotelKey]` from the envelope, if present
     (deeplink to the SEO catalog row).
3. Use a snapshot table keyed by `(hotelKey, SystemKey, snapshot_ts)`.
4. In the existing `snapshot_farvater` calendar pipeline, **join on
   `hotelKey`** at read-time (in `deal_service` or in a materialised view).
   The calendar already includes `systemKey` per date row — if you want a
   tighter join, the `static-tours` tour-level `SystemKey` can be matched
   against per-date `systemKey` strings (both follow the
   `2p<digits>c<country>` shape, e.g.
   `2p4191025733778095065c51`).

`hotelSpecialLinx` returned in the envelope also gives you a per-hotel
canonical CTA URL like
`/getsearchcataloglink/gorjashhie-tury_iz-goroda-warszawa_v-otel-15937` —
worth surfacing in deal cards.

Cost: with `pageSize=50`, sweeping `gorjashhie-tury` (635 tours, 13 pages),
`rannee-bronirovanie` (1668 tours, 34 pages) and `akcionnye-tury` (50 tours,
1 page) once per country-of-interest is ~50 requests per full sweep. At a 2-s
politeness sleep that's ~100 s wall time. Very cheap relative to the existing
per-hotel calendar fan-out.

---

## Schema Snapshots

### `/uk/catalog/static-tours` request (POST, JSON body)

```http
POST /uk/catalog/static-tours HTTP/1.1
Host: farvater.travel
Content-Type: application/json
X-Requested-With: XMLHttpRequest
Referer: https://farvater.travel/uk/gorjashhie-tury_tury-v-stranu-turtsiya/
Origin: https://farvater.travel
```
```json
{
  "nightFrom": 0,
  "nightTo": 0,
  "slugTypes": ["gorjashhie-tury"],
  "countryId": -1,
  "starIDs": [],
  "meals": [],
  "adults": 2,
  "kids": 0,
  "ages": [],
  "hotels": [],
  "resorts": [],
  "airportList": [],
  "operatorIdList": [],
  "checkinList": [{
    "From": "2026-05-25T00:00:00+03:00",
    "To":   "2026-06-17T00:00:00+03:00"
  }],
  "pageSize": 50,
  "pageIndex": 1,
  "descByPrice": false
}
```
No CSRF token, no `sCode`, no cookie dance was required. A vanilla
chrome120-impersonated request from a cold session succeeded.

### `/uk/catalog/static-tours` response shape (anonymized, one tour shown)

```json
{
  "success": true, "statusCode": 200, "statusMessage": null,
  "data": {
    "tourPackage": {
      "tours": [{
        "disablePromoCode": false,
        "HotType": 1, "EarlyType": 1, "RecommendedType": 1,
        "isHot": true, "isPromo": false, "isVip": false, "isBestDeal": false,
        "LoadedDate": "2026-05-24T22:56:42.853+03:00",
        "operatorName": "Alliance", "operatorIdInt": 119, "currencyIdInt": 4,
        "operatorId": "{AllianceNativeApi}", "type": "plain",
        "cityFromCode": "WAW", "cityFromName": "Варшава", "flyInclude": "true",
        "countryID": "51", "countryName": "Мальдіви",
        "countryNameAccusativeCase": "на Мальдіви",
        "checkIn": {"value": "2026-06-11T00:00:00+03:00", "hash": -1086273733},
        "region": {
          "RegionName": "Мале", "ResortName": "Південний Мале Атол",
          "RegionHash": 360, "ResortHash": 767,
          "value": "Мале Південний Мале Атол", "hash": 1622483142
        },
        "hotel": {"hash": 1700631576, "value": "ANONYMIZED"},
        "hotelId": 0, "hotelUrl": "/hotel/xx/anonymized", "hotelKey": "XXXXX",
        "star": {"hash": 4, "value": "4"},
        "meal": {"hash": 0, "value": "Сніданок (BB)"},
        "room": "Standard Room (no window or Balcony)",
        "htplace": "2 AD",
        "price": 664, "customPriceWd": 0, "customPriceWdUah": 0,
        "currency": "USD", "priceUAH": 29847, "nights": 9,
        "address": "Южный Мале Атолл",
        "photo": "https://img4.farvater.travel/mapkey/XXXXX/0?size=catalog",
        "rate": "8,4",
        "adl": 2, "kids": 0, "ages": "", "chd": 0,
        "isEarly": false,
        "SystemKey": "2p4191025733778095065c51",
        "othersAgr": [], "other": [],
        "isRecommended": true, "IsChoiceFarvater": false,
        "FarTourId": 286586304, "sort": 0,
        "IsFreePCRTest": false, "IsBlackFriday": false, "AdditionalInfo": null,
        "idsForText": {
          "roomId": 2076065, "htplaceId": 2003989, "mealId": 0, "starId": 4,
          "countryid": 51, "longhotelId": 15937, "airportId": 28,
          "transferTypeId": 1, "touristsBits": 2,
          "reviewsCount": "1100", "currencyId": 4
        },
        "redPriceUAH": 29847, "countOther": -1,
        "latitude": 3.9454539, "longitude": 73.4917733,
        "next": null, "prev": null,
        "tourFreeCancel": false, "isOtp": true,
        "HealthCertificate": false, "WorksIn2020": false,
        "promotionEndDate": null, "isLastSeats": false
      }],
      "totalItems": 635, "minPrice": 29847, "maxPrice": 82975,
      "pageSize": 50, "hashId": "00000000-0000-0000-0000-000000000000",
      "pagesCount": 13
    },
    "hotelDescription": {},
    "hotelSpecialLinx": {
      "XXXXX": "/getsearchcataloglink/gorjashhie-tury_iz-goroda-warszawa_v-otel-XXXXX"
    }
  }
}
```

Full live (non-anonymized) capture: `/tmp/farvater-har/_static-tours-all.json`
(94 KB, 50 tours).

### `/uk/tour/stat/low-price-calendar/auto` response shape (live, hotelKey=15937)

```json
{
  "statusCode": 200,
  "data": {
    "hotel": "/hotel/mv/arena-beach-hotel-spa",
    "currency": {"code":"EUR","symbol":"€","name":"Євро"},
    "items": [{
      "item": {
        "night": 7,
        "dates": [
          {"date":"18.06.2026","price":2474,"priceUAH":111924,"day":"Чт","meal":"BB","room":"STANDARD (NO WINDOW OR BLC)","systemKey":"2p7770964832703134606c51"},
          {"date":"19.06.2026","price":2474,"priceUAH":111924,"day":"Пт","meal":"BB","room":"STANDARD (NO WINDOW OR BLC)","systemKey":"2p7820912721968838154c51"}
        ]
      }
    }],
    "hasMore": false,
    "hash": [],
    "minDate": null,
    "dateShift": 14,
    "syncType": 0
  }
}
```

Full live capture: `/tmp/farvater-har/_calendar-15937-hot.json`.

---

## Anomalies / Risks

- **`/tours/getminprice/?genId={hotelKey}` is dead.** All 9 probes returned a
  200-status HTML "500 Технические работы" page (~2.8 KB). It is not a useful
  endpoint in 2026-05. Do not include it in the new pipeline.
- **`/sitemap-hotelpages-3.xml` (and -1, -2) returns 404.** The "baseline
  hotels" half of the original sampling plan was unavailable. The
  investigation pivoted to comparing slugType buckets within `static-tours`
  instead, which is in fact a cleaner basis for the coverage matrix.
- **`/uk/gorjashhie-tury_*` SSR HTML is misleading.** It contains 50 hotel
  cards as a `hotels:[...]` JSON literal in the script bundle, but with
  `isHot:false, priceUAH:0` on every card. They are skeletons. Scraping this
  HTML and extracting flags from the inline JSON will give a wrong "no hot
  tours exist" answer. The real data only appears after the page makes the
  follow-up `static-tours` POST.
- **`var TModel = {...}` on hotel pages has the right schema but placeholder
  values.** Same skeleton trap. Do not scrape promo flags from hotel pages —
  they will always read `false / 0`.
- **`redPriceUAH` is semantically unclear.** In 50/50 hot-tour samples it
  equals `priceUAH`. The name suggests a "red-highlighted strike-through old
  price", but evidence does not support that interpretation in 2026-05. Capture
  the value, but do not surface a "-X % off" badge based on `redPriceUAH !=
  priceUAH` until a real diverging sample is observed.
- **`isOtp` semantic is unclear.** Likely "On-the-Phone" (last-seats /
  request-to-confirm tour). Comes in at 46 % among hot tours. Worth surfacing
  but label cautiously — confirm meaning with a farvater operator-facing
  account before promoting it to a user-facing badge.
- **`isPromo` is in the schema but never `true`** in 200 tour rows across 4
  bucket queries. Could be (a) deprecated, (b) only populated for B2B
  partners. Capture the field for completeness but do not gate any logic on
  it.
- **`actionPrice`, `oldPriceUAH`, `isAction` named in the task brief do
  not exist on farvater.** Update downstream specs.
- **Cloudflare / WAF:** none encountered during this probe. All requests
  succeeded on the first try with `curl_cffi.requests.Session(impersonate=
  "chrome120")` and the documented `FastTravel-HAR-Probe/0.1` UA. No `sCode`
  cookie dance was required for any of the JSON endpoints. **This may change
  under sustained load** — the SEO catalog page does bootstrap an
  `sCodeStorage` JS object that is used for other endpoints (search-form
  submit flow), so production code should be defensive and capable of doing
  the `sCode` dance if `static-tours` ever starts rejecting cold requests.
- **`hashId` is the zero GUID** in our response
  (`00000000-0000-0000-0000-000000000000`). It is probably a search-session
  identifier used when the page later requests a `static-statistic` refresh
  with the same hash. Not needed for promo capture.
- **Country coverage:** a single `countryId=-1` sweep returned tours from
  Turkey, Greece, UAE, Spain, Maldives, Egypt. For per-country isolation
  (e.g. only Turkey hot tours), set `countryId` explicitly — but the country
  ID space (Turkey ≈ ?, Egypt ≈ ?, etc.) was not enumerated in this probe.
  The country IDs are exposed on each returned tour row as `countryID`
  (string) and `idsForText.countryid` (int) — sweep `countryId=-1` once to
  discover them, then narrow as needed.

---

## Appendix: Provenance

- Probe scripts: `/tmp/farvater-har/probe.py`, `/tmp/farvater-har/probe2.py`,
  `/tmp/farvater-har/analyze.py`
- Raw responses: `/tmp/farvater-har/*-page.html` (9 hotel pages),
  `*-calendar.json`, `*-getminprice.json`, `_hot-listing.html`,
  `_static-tours-all.json`, `_calendar-15937-hot.json`,
  `_script_V4SEOcatalog.js`, `_script_NewV4.js`
- Anonymized canonical sample: `/tmp/farvater-har/_sample_static_tour.json`
- Manifest: `/tmp/farvater-har/_manifest.json`
- Total requests issued: ~30 (well under the 100-request budget)
- HTTP client: `curl_cffi==0.7.4`, `impersonate="chrome120"`
- Politeness: 2.2 s sleep between every request to `farvater.travel`
- User-Agent: `FastTravel-HAR-Probe/0.1 (+https://fasttravel.example/about)`
