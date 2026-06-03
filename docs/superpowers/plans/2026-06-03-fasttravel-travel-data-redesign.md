# FastTravel Travel + Data Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first verified web slice of the approved Travel + Data redesign: header, homepage hero/search/calendar preview, and refreshed tour/deal cards.

**Architecture:** Keep the existing Next.js/Tailwind stack and server/data flow. Add small focused presentational components for the hero calendar preview, trust strip, and redesigned surface primitives instead of turning `page.tsx` into a monolith.

**Tech Stack:** Next.js 15, React 19, Tailwind v3, Vitest/Testing Library, Browser in-app QA.

---

## File Structure

- Modify `apps/web/src/components/layout/Header.tsx` for a cleaner brand mark and Travel + Data nav treatment.
- Modify `apps/web/src/app/page.tsx` for the new first viewport, live preview rail, and section rhythm.
- Modify `apps/web/src/components/SearchForm.tsx` to support a homepage redesign variant while preserving URL behavior.
- Modify `apps/web/src/components/DealCard.tsx` and `apps/web/src/components/HotelCard.tsx` for the brighter Travel + Data card language and no emoji placeholders.
- Modify `apps/web/src/styles/globals.css` and `apps/web/tailwind.config.ts` only for design tokens that are reused across components.
- Add or update focused tests in `apps/web/src/components/*.test.tsx`.

## Task 1: Structural Tests For The Redesign Slice

**Files:**
- Modify: `apps/web/src/components/SearchForm.test.tsx`
- Modify: `apps/web/src/components/DealCard.test.tsx`
- Modify: `apps/web/src/components/HotelCard.test.tsx`

- [ ] Add tests that prove `SearchForm` can render the Travel + Data hero variant without breaking existing submission behavior.
- [ ] Add tests that prove `DealCard` no longer relies on emoji method icons in the visible badge and still preserves sponsored-link disclosure.
- [ ] Add tests that prove `HotelCard` exposes scan-friendly price/freshness facts and keeps a non-emoji no-photo placeholder.
- [ ] Run the focused tests and verify they fail for the intended missing redesign behavior.

## Task 2: Header And Homepage Hero

**Files:**
- Modify: `apps/web/src/components/layout/Header.tsx`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/styles/globals.css`

- [ ] Replace the emoji brand mark with a code-native mark.
- [ ] Rebuild the homepage first viewport around Travel + Data: copy, search, destination imagery, and a calendar heatmap preview.
- [ ] Keep existing data fetching and ISR behavior intact.
- [ ] Run the focused homepage/component tests.

## Task 3: Search Form Variant

**Files:**
- Modify: `apps/web/src/components/SearchForm.tsx`
- Test: `apps/web/src/components/SearchForm.test.tsx`

- [ ] Add a conservative `variant` prop for homepage styling without changing default search-page behavior.
- [ ] Keep field labels, URL sanitization, `useTransition`, and `router.push` behavior unchanged.
- [ ] Run `SearchForm.test.tsx`.

## Task 4: Card Visual Language And Trust Signals

**Files:**
- Modify: `apps/web/src/components/DealCard.tsx`
- Modify: `apps/web/src/components/HotelCard.tsx`
- Test: matching component tests.

- [ ] Remove visible emoji dependency from deal badges and no-photo fallbacks.
- [ ] Refresh result cards for scanability: image, destination/rating, price, freshness, and action.
- [ ] Preserve honest baseline and sponsored-link behavior.
- [ ] Run `DealCard.test.tsx` and `HotelCard.test.tsx`.

## Task 5: Rendered QA

**Files:**
- No committed QA artifacts.

- [ ] Start the web dev server.
- [ ] Open homepage in the in-app Browser.
- [ ] Check page identity, nonblank content, no framework overlay, console health, screenshot evidence, and one interaction.
- [ ] Check one mobile viewport.
- [ ] Compare against the accepted Travel + Data concept and record remaining visual deviations.
