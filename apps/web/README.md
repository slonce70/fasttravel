# `apps/web/` — FastTravel Next.js frontend

Next.js 15 (App Router) + TypeScript + Tailwind v3 + TanStack Query v5, deployed to **Cloudflare Pages** via `@cloudflare/next-on-pages`. Single locale (`uk`), dark mode out of scope on MVP.

The moat component is `src/components/PriceCalendar.tsx` — a `react-day-picker` v9 calendar with a custom `DayButton` that paints each cell with a HSL heatmap color (cheap = green, expensive = red) derived from the visible window's price percentile.

---

## Local development

Prereqs: Node ≥ 20.11, pnpm 9.

```bash
cd apps/web
pnpm install
cp .env.example .env.local       # set NEXT_PUBLIC_API_URL if backend isn't on :8000
pnpm dev                          # → http://localhost:3000
```

The backend must be reachable at `NEXT_PUBLIC_API_URL`. Spin it up via the root `docker-compose.yml` (Postgres + Redis + FastAPI), then `cd apps/api && poetry run uvicorn src.main:app --reload`.

Useful scripts:

```bash
pnpm typecheck      # tsc --noEmit
pnpm lint           # eslint via next lint
pnpm format         # prettier --write
pnpm build          # next build (server runtime)
pnpm pages:build    # @cloudflare/next-on-pages adapter → .vercel/output/static
pnpm pages:preview  # wrangler pages dev against the built artefact
```

---

## Deployment to Cloudflare Pages

> Setup once the user has an account.

1. **Create the project in Cloudflare dashboard.** Pages → Create → Connect to Git → pick the repo → choose `apps/web/` as the build directory.
2. **Build settings:**
   - Build command: `pnpm install --frozen-lockfile && pnpm pages:build`
   - Build output directory: `.vercel/output/static`
   - Root directory: `apps/web`
   - Node version env var: `NODE_VERSION=20`
3. **Environment variables** (Pages dashboard → Settings → Environment variables):
   - `NEXT_PUBLIC_API_URL=https://api.fasttravel.com.ua` (production)
   - For preview branches the value is overridden by `wrangler.toml` (`[env.preview.vars]`).
4. **Compatibility flags** (Pages dashboard → Settings → Functions): enable `nodejs_compat`. The same is already mirrored in `wrangler.toml` for `wrangler pages dev`.
5. **KV namespace binding for ISR.** Pages → Settings → Functions → KV namespace bindings → add one named `NEXT_CACHE_WORKERS_KV` (create a new KV namespace in Workers KV first). Without this binding `@cloudflare/next-on-pages` falls back to non-persistent cache and `revalidate` becomes a no-op at the edge.
6. **Custom domain.** Pages → Custom domains → add `fasttravel.com.ua`. Cloudflare wires the cert automatically.

For one-off deploys from your laptop: `pnpm pages:deploy` (uses `wrangler`).

---

## Architecture notes

- **API contract is mirrored in `src/lib/types.ts`.** Keep in sync with `apps/api/src/schemas/*.py` (snake_case preserved — no translation layer).
- **Pages are SSG/ISR where possible.** Hotel page revalidates every 1h; deals every 5 min; home every 10 min. Calendar data inside the hotel page is client-fetched via TanStack Query so it refreshes independently of the page cache.
- **Image optimization disabled.** `next/image` requires Sharp which isn't available on Cloudflare's edge runtime. We use plain `<img>` and rely on the CDN; Phase 2 plan is to route through Cloudflare Image Resizing.
- **No middleware on MVP.** Avoids the 1 MB edge-runtime bundle limit. Add only when a concrete need appears (geo-routing, auth).
- **Search and deal cards link to operator sites with `rel="nofollow sponsored noopener"`** in line with our affiliate model.

---

## Backend follow-ups discovered during this build

These are real gaps the frontend papers over today; they should land as follow-up tasks on `apps/api/`:

1. **`GET /api/deals/{id}` endpoint.** `/deals/[id]` permalink today pages through `?limit=200` and filters client-side. Fine for low-hundreds/day; not fine once volume grows or SEO matters.
2. **`DealOut.hotel_slug` and `DealOut.hotel_name`.** Today `DealCard` shows `Готель #42` and links to `/hotels/{numeric_id}` which 404s (hotel router expects a slug). Adding both fields makes deal cards self-contained and indexable.
3. **Calendar meal-plan filter — clarify.** Frontend has a meal-plan chip in the hotel filters but the `/calendar` endpoint ignores it (only `from`/`to`). The current code uses meal-plan only for the offers fetch. Decide whether the calendar should pre-filter by meal (smaller payload, more precise heatmap) or stay aggregated.

---

## New ADRs to add to `docs/DECISIONS.md`

I deviated slightly from the task spec for two pragmatic reasons; record them as ADRs once you review:

- **ADR-015: Tailwind v3 (not v4) on the frontend skeleton.** v4 ships CSS-first config (`@theme` directive in globals.css) and replaces `tailwind.config.ts` plus `postcss` plugin with `@tailwindcss/postcss`. The task asks for a `tailwind.config.ts` layout, so I pinned `tailwindcss@^3.4.14`. v4 is fine, but a skeleton isn't the right place to break new ground — re-evaluate when the design system stabilizes.
- **ADR-016: `react-day-picker` v9 — custom `DayButton` (not `DayContent`).** v9 removed `DayContent`; the heatmap renderer lives in a `components.DayButton` override (`PriceCalendar.tsx :: PriceDayButton`). The button receives `day`/`modifiers` and renders price + emoji + background color inline.

---

## First-install verifications

After `pnpm install` succeeds, sanity-check the following — they're version-sensitive paths that won't surface until runtime:

1. **`react-day-picker` CSS path.** `PriceCalendar.tsx` imports `'react-day-picker/style.css'`. If that throws "module not found", check `node_modules/react-day-picker/package.json` exports field — older v9 minors used `'react-day-picker/dist/style.css'`. Update the import accordingly.
2. **`@tanstack/react-query` v5 object-syntax.** All hooks use `useQuery({ queryKey, queryFn })`. If you upgrade to a v4 by accident, you'll see "Property 'queryKey' is missing" errors at compile time.
3. **`next/font/google` on Cloudflare.** Inter is loaded via `next/font/google`. If `pnpm pages:build` fails on font fetch, switch to the `geist` package (no remote fetch during build).

## TODOs

- Playwright e2e tests for the hotel-page flow: open `/hotels/[slug]` → select a date in the calendar → confirm an offer renders → click "Купити" opens external link.
- Sentry browser SDK integration in `src/app/error.tsx`.
- `/api/sitemap.xml` route once the hotel catalogue is populated (target: 300 entries).
- Migrate to `next/image` if/when Cloudflare Image Resizing is wired up (Phase 2).
- Real `favicon.ico`, `apple-touch-icon.png`, `og-default.png` assets.
- Cloudflare Pages-side cache rule for `/api/hotels/*/calendar` once the backend is on the public domain (Phase 2 cost optimization).
