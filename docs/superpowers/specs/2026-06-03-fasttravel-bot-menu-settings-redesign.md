# FastTravel Telegram Bot — Menu & Settings Redesign

**Date:** 2026-06-03
**Status:** implemented (commits `84f7e43`, `be03456`)
**Surface:** `apps/bot` (aiogram 3) + one keyboard-only edit in `apps/scheduler`

## Purpose

The bot's main-menu information architecture was confusing and partly dishonest,
and `/profile` was a stub (ID + sub count + GDPR delete) with no real settings.
This redesign clarifies the menu, adds a proper account hub, and ships the
notification controls users actually need — all as **chrome**, with zero DB
migration and without touching the owner-governed deal detector.

## Governance boundary (hard constraint)

The deal-detection engine is owner-governed and was **not** touched. Off-limits:
detection thresholds, what `/best` vs `/deals` vs `/cheap` *select*, the notify
job's `_MATCH_SQL` / selection / ordering / `MAX_PER_RUN`, and the semantic
content of any deal/alert/price copy (`templates/deal.py`, `templates/cheap.py`,
`DealCard` signal copy, the calendar dip-hint wording). Relabeling a menu button
and recoloring a marker are presentation (in scope); changing what a command
surfaces or asserts is selection (out of scope). See `feedback_detection_core_governance`.

## Menu / IA changes (presentation only — every button keeps its handler)

- `CHEAP` `🔥 Найдешевші тури` → **`💰 Найдешевші тури`** — the 🔥 falsely implied a
  discount; `/cheap` shows absolute «ціна від», never a discount. 💰 matches the
  price-from framing and de-collides from `DEALS` (both previously used 🔥).
- `DEALS` `🔥 Усі варіанти` → **`🔥 Гарячі тури`** (keeps 🔥 unique, aligns with the feed header).
- `BEST` `🏆 ТОП варіанти` → **`🏆 Топ зараз`**.
- `SUBSCRIBE` `🔔 Підписки на варіанти` → **`🔔 Мої підписки`** (matches the profile button).
- Reply keyboard regrouped into clusters: `[Пошук, Напрямки]` / `[Топ, Гарячі, Найдешевші]` / `[Мої підписки, Профіль, Допомога]`.
- BotFather `/`-menu descriptions synced; `/help` now lists `/cheap`; `/settings`
  added as an alias to the account hub.

## Account hub (`/profile` + `/settings`)

A single hub: greeting, active-subscription count, an optional read-only
"🕓 Останній алерт: <date>" (from `telegram_filter_notifications.sent_at` via a
join on `telegram_subscriber_filters`), and rows for Мої підписки / ⏸ Сповіщення /
📡 Канал / 🗑 Видалити всі дані. The GDPR delete-confirmation flow is preserved.

## Notification controls (zero migration)

The enforcement gate already exists: `notify_subscribers` filters `WHERE f.is_active`,
and `telegram_subscribers.filters_jsonb` (JSONB, previously unused) is a free
preference store.

- **Per-subscription mute** — toggle `is_active` on a single filter (🔕 Призупинити /
  🔔 Увімкнути) from the subscriptions list and from each scheduler alert
  (`sub:mute:{filter_id}`); muted subs render "(на паузі)". No scheduler logic change —
  the alert keyboard just gained one button.
- **Global pause** — `⏸ Сповіщення` submenu: 24 год / 7 днів / поки не ввімкну.
  Bulk-deactivates only currently-active filters, records their ids + expiry under
  a `"pause"` key in `filters_jsonb`, and resumes **only** those ids (never a sub
  the user muted on purpose). Timed pauses expire **lazily** on the user's next
  interaction (no cron) — a timed pause therefore lasts *at least* its window.
- **Edit subscription** — `✏️ Змінити` re-opens the add wizard for that filter.

## Deliberately deferred / out of scope

- Quiet-hours enforcement and per-day alert caps — these would require editing the
  owner-governed `_MATCH_SQL`; deferred behind sign-off (YAGNI for a low-volume,
  $0 product whose volume is already bounded by `MAX_PER_RUN` + per-filter DISTINCT ON).
- A subscription display-name/label — the one management feature that would need a
  migration; subs are legible by flag + budget + stars at current scale.
- Bot color/theme (Telegram chrome is uncolorable) and i18n/language toggle (single
  uk market). What carries from the web redesign is the honest, restrained *voice*,
  not tokens.

## Verification

`ruff check --no-cache` + `mypy` + `pytest` green for bot (158) and scheduler (298);
pause/resume semantics additionally verified against the real test DB.
