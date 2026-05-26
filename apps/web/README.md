# `apps/web/` — FastTravel Next.js frontend

Next.js 15 (App Router) + TypeScript + Tailwind v3 + TanStack Query v5, deployed to **Cloudflare Workers** via `@opennextjs/cloudflare`. Single locale (`uk`), dark mode out of scope on MVP.

The moat component is `src/components/PriceCalendar.tsx` — a `react-day-picker` v9 calendar with a custom `DayButton` that paints each cell with a HSL heatmap color (cheap = green, expensive = red) derived from the visible window's price percentile.

---

## Local development

Prereqs: Node ≥ 20.11, pnpm 9.

```bash
cd apps/web
pnpm install
cp .env.example .env.local       # set public API / Telegram URLs if needed
pnpm dev                          # → http://localhost:3000
```

The backend must be reachable at `NEXT_PUBLIC_API_URL`. For the repo-standard
local path, run the root compose API and point the frontend at it:

```bash
cd /Users/trend/Documents/Work/fasttravel
cp .env.example .env
docker compose up -d postgres redis
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up -d api

cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
```

Useful scripts:

```bash
pnpm typecheck      # tsc --noEmit
pnpm lint           # eslint via next lint
pnpm format         # prettier --write
pnpm build          # next build (server runtime)
pnpm cf:build       # OpenNext adapter → .open-next/worker.js + assets
pnpm cf:preview     # build + local Workers runtime preview
```

---

## Deployment to Cloudflare Workers

> Setup once the user has an account.

1. **Create the Worker deployment in Cloudflare.** Use the OpenNext/Workers flow for the repo and set `apps/web/` as the root directory.
2. **Build settings:**
   - Build command: `pnpm install --frozen-lockfile && pnpm cf:build`
   - Root directory: `apps/web`
   - Node version env var: `NODE_VERSION=20`
3. **Environment variables** (Worker environment variables / `wrangler.jsonc`):
   - `NEXT_PUBLIC_API_URL=https://api.fasttravel.com.ua` (production)
   - `NEXT_PUBLIC_TELEGRAM_CHANNEL_URL=https://t.me/testtyhhh` (production channel CTA + QR)
   - Preview values live under `env.preview.vars` in `wrangler.jsonc`.
4. **Compatibility flags.** Keep `nodejs_compat` and `global_fetch_strictly_public`; both are already in `wrangler.jsonc`.
5. **Caching.** OpenNext can use R2 for incremental/cache persistence later. MVP deploy keeps the adapter's default cache path; add an R2 binding only when the production account is ready.
6. **Custom domain.** Add `fasttravel.com.ua` to the Worker route/custom domain after `api.fasttravel.com.ua` is live on the VPS. The Worker should not own the API host.

For CI deploys, configure `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`
as GitHub Actions secrets. `.github/workflows/deploy-web.yml` then runs audit,
lint, typecheck, Vitest, OpenNext build, a Wrangler dry-run, and finally
`pnpm cf:deploy` on `main` pushes that touch `apps/web/**`. Manual
`workflow_dispatch` can also deploy the `preview` Worker via
`pnpm cf:deploy:preview`. Add `FRONTEND_PRODUCTION_URL` and optionally
`FRONTEND_PREVIEW_URL` as repository variables/secrets to run Playwright smoke
against the deployed URL inside the same job. `NEXT_PUBLIC_API_URL` and
`NEXT_PUBLIC_TELEGRAM_CHANNEL_URL` are also passed at build time in CI because
Next.js public env can be embedded in the generated bundle.

For one-off deploys from your laptop: `pnpm cf:deploy`. Preview Worker deploys use
`pnpm cf:deploy:preview`.

---

## Architecture notes

- **API contract is mirrored in `src/lib/types.ts`.** Keep in sync with `apps/api/src/schemas/*.py` (snake_case preserved — no translation layer).
- **Pages are SSG/ISR where possible.** Hotel page revalidates every 1h; deals every 5 min; home every 10 min. Calendar data inside the hotel page is client-fetched via TanStack Query so it refreshes independently of the page cache.
- **Image optimization disabled.** `next/image` would need additional Cloudflare Images wiring. We use plain `<img>` and rely on the CDN; Phase 2 plan is to route through Cloudflare Images.
- **No middleware on MVP.** Avoids the 1 MB edge-runtime bundle limit. Add only when a concrete need appears (geo-routing, auth).
- **Search and deal cards link to operator sites with `rel="nofollow sponsored noopener"`** in line with our affiliate model.

---

## API contract notes

- Hotel calendars accept `?meal_plan=` / `?meal=` and the backend filters the
  heatmap through `hotel_calendar_prices.meal_plan`.
- Tailwind v3 and the `react-day-picker` v9 `DayButton` override are recorded
  in `docs/DECISIONS.md` as ADR-015 and ADR-016.

---

## First-install verifications

After `pnpm install` succeeds, sanity-check the following — they're version-sensitive paths that won't surface until runtime:

1. **`react-day-picker` CSS path.** `PriceCalendar.tsx` imports `'react-day-picker/style.css'`. If that throws "module not found", check `node_modules/react-day-picker/package.json` exports field — older v9 minors used `'react-day-picker/dist/style.css'`. Update the import accordingly.
2. **`@tanstack/react-query` v5 object-syntax.** All hooks use `useQuery({ queryKey, queryFn })`. If you upgrade to a v4 by accident, you'll see "Property 'queryKey' is missing" errors at compile time.
3. **`next/font/google` on Cloudflare.** Inter is loaded via `next/font/google`. If `pnpm cf:build` fails on font fetch, switch to the `geist` package (no remote fetch during build).

## Follow-up Backlog

- Sentry browser SDK integration in `src/app/error.tsx`.
- Migrate to `next/image` if/when Cloudflare Image Resizing is wired up (Phase 2).
- Real `favicon.ico`, `apple-touch-icon.png`, `og-default.png` assets.
- Cloudflare cache rule for `/api/hotels/*/calendar` once the backend is on the public domain (Phase 2 cost optimization).

## Browser smoke

```bash
pnpm test:e2e:install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm test:e2e
```

The default test server uses `127.0.0.1:3100`, so it cannot accidentally hit
another local app already listening on `localhost:3000`. For staging/prod
smoke, point the same suite at a deployed frontend:

```bash
WEB_E2E_BASE_URL=https://fasttravel.com.ua pnpm test:e2e
```
