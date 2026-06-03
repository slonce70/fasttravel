# FastTravel Travel + Data Redesign

**Date:** 2026-06-03  
**Status:** approved direction, pending implementation plan  
**Chosen concept:** B. Travel + Data  
**Concept artifact:** `docs/superpowers/specs/assets/2026-06-03-fasttravel-travel-data-redesign-concept.png`

## Purpose

Redesign the FastTravel web experience so it feels like a premium travel product with a strong data
advantage: emotional enough to make people want the trip, precise enough to make them trust the
price. The site should not look like a generic tour agency landing page. The signature product
moment is still the price calendar and honest cheap-date detection.

## Product Position

FastTravel is an information aggregator and price-discovery layer, not a booking engine. The
redesign must make three things obvious:

- Users search tours and cheap dates, then buy from the operator via outbound links.
- Cheap-date and deal signals are data-backed and explained in plain Ukrainian.
- The calendar is the product moat, not a supporting decoration.

The main promise is: **find unusually good travel dates faster, with enough context to trust the
price.**

## Design Direction

Use the selected **Travel + Data** concept as the primary direction:

- Bright, high-trust, travel-forward first viewport.
- Resort/hotel imagery integrated into the layout, never used as a dark generic background.
- A prominent price calendar or heatmap module visible in the first screen.
- A search panel that feels like a real tool, not a marketing form.
- Small destination or hotel preview rail to show the catalog is live and specific.

Guardrail: the site may feel warmer and more aspirational than the current UI, but the product
surface remains search/calendar/results first. Avoid the standard travel-site pattern of a large
photo hero with centered text and a floating booking form.

## Homepage

The homepage first viewport should be rebuilt around a split but integrated composition:

- Header: simple brand, essential nav (`Пошук`, `Знижки`, `Напрямки`, `Telegram`) and one primary
  action. Replace emoji brand/icon treatment with a small code-native mark or clean SVG glyph.
- Hero copy: concrete and short. Lead with finding cheap dates, not selling tours generally.
- Search: preserve current fields (`country`, `check_in`, `nights`, `tourists`, `meal_plan`,
  `price_max`, `stars_min`) but visually group them into a calmer panel with stronger labels and
  better field hierarchy.
- Calendar preview: show a realistic heatmap-style calendar preview with green/yellow/red date
  cells, a clear legend, and one highlighted cheap date.
- Trust microcopy: add one compact explanation such as `нижче за сусідні дати` or
  `ціна оновлена сьогодні`; never imply a fake old price.
- Next-section preview: the first viewport should leave the beginning of a live offers/deals rail
  visible, so users see real tour content immediately.

## Search And Results

The selected concept is warmer than a pure console, but `/search` should borrow the density and
scanability of the third concept:

- Keep filters visible and compact; do not hide critical search controls behind decorative UI.
- Move results away from generic equal-height card grids where possible. Use a scan-friendly
  list/card hybrid with thumbnail, hotel name, destination, stars, review score, price, nights,
  meal, freshness, and primary action.
- Sorting and empty/error states should be first-class: loading skeletons match final layout,
  empty states explain which filters to relax, and errors are inline.
- Avoid inflated discount visuals on search results. Use discount/deal indicators only when the
  backend signal is trustworthy and labelled.

## Hotel Detail

The hotel page should become the strongest proof of the product:

- Top section: hotel media, key facts, current lowest price, and direct operator action.
- Calendar section: larger, more legible, and less boxed-in than the current component. The heatmap
  should feel like the center of the page.
- Controls: nights, meal plan, and selected date stay connected to calendar and offers. Use clear
  segmented/chip controls, but avoid over-rounded pill clutter.
- Offers: show operator rows with price, date, nights, meal, room category, freshness, and outbound
  action. The user should understand exactly what will be bought elsewhere.

## Deal Cards And Honesty

All cards and deal surfaces must preserve FastTravel's recent honesty work:

- `calendar_anomaly` / date-dip signals can show a baseline explanation for neighboring dates.
- Weak peer-style comparisons should not look like the same quality of discount.
- Old-price strike-through appears only when the signal contract says it is honest.
- Sponsored/outbound link labelling remains visible.
- Copy should say what the system knows, not what a marketing page wishes were true.

## Visual System

Use a bright neutral foundation:

- Background: true white or near-white neutral, not beige/sand and not dark-blue slate.
- Text: charcoal/off-black, not pure black.
- Primary accent: restrained teal/green for search, selected date, and positive price moments.
- Secondary accent: small amber/coral for hot-date emphasis only.
- Avoid purple/blue AI gradients, neon glows, decorative blobs/orbs, and one-note blue pages.

Typography:

- Move away from the current default Inter feel. Prefer a modern sans with more character, such as
  Geist or a similar `next/font` option that supports Cyrillic cleanly.
- Hero type should be confident but not oversized. Use hierarchy through weight, spacing, and
  layout, not only huge text.
- UI chrome text for filters, tabs, buttons, and calendar cells must be deliberately sized; no
  browser-default control typography.

Containers:

- Use cards only for real repeated items, result rows, modals, or framed tools.
- Avoid nested cards.
- Calendar and search can be framed as product modules, but page sections should otherwise breathe
  as full-width bands or open layouts.

Imagery:

- Use real-looking resort/hotel/destination images in stable aspect ratios.
- Images support context; they do not cover the interface or reduce price legibility.
- Avoid dark overlays and cropped stock-photo moods that make the product harder to inspect.

## Motion And Interaction

Motion should be useful and restrained:

- Filter/button active states should feel tactile.
- Calendar date hover/selection can animate via transform/opacity only.
- Results can use subtle reveal or skeleton transitions, respecting `prefers-reduced-motion`.
- Do not add heavy continuous animation or cursor effects.

## Responsive Rules

Mobile must keep the product usable:

- Search fields collapse into a clean single-column or two-column rhythm without horizontal scroll.
- Calendar preview becomes a compact strip or one-month view; it should not overflow.
- Result cards become a vertical list with price and action visible without opening detail.
- Header keeps only brand plus the highest-value actions.

## Technical Fit

Existing stack: Next.js 15, React 19, Tailwind v3, TanStack Query. The redesign should stay inside
that stack unless the implementation plan explicitly justifies a new dependency.

Component areas likely affected:

- `apps/web/src/app/page.tsx`
- `apps/web/src/components/SearchForm.tsx`
- `apps/web/src/components/DealCard.tsx`
- `apps/web/src/components/HotelCard.tsx`
- `apps/web/src/components/PriceCalendar.tsx`
- `apps/web/src/app/search/page.tsx`
- `apps/web/src/app/hotels/[slug]/HotelView.tsx`
- `apps/web/src/components/layout/Header.tsx`
- `apps/web/src/styles/globals.css`
- `apps/web/tailwind.config.ts`

Do not implement the redesign as one giant page file. Build reusable primitives for:

- search fields and form layout
- calendar legend/date cells
- deal/trust signal labels
- offer/result rows
- media frames
- section shells

## Verification

Implementation should be verified visually and functionally:

- Browser screenshot comparison against the selected concept.
- Desktop and mobile viewport checks.
- Homepage first viewport with next-section preview visible.
- `/search` with non-empty, empty, loading, and error states.
- Hotel detail calendar interaction: nights, meal plan, selected date, refresh state.
- Deal-card honesty checks: no fake strike-throughs, no misleading discount labels.
- Existing web tests plus focused render tests where component behavior changes.

## Out Of Scope

- Native checkout.
- New booking/payment flow.
- Rewriting the deal detector.
- Inventing new discount claims not backed by existing API fields.
- Adding a heavy animation framework before the implementation plan proves it is needed.
