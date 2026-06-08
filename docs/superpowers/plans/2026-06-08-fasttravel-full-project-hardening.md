# FastTravel Full Project Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** усунути найризиковіші точки дублювання production-логіки, покращити стійкість scheduler/API/bot/web, закріпити UX-контракти тестами і залишити проект у стані, який можна безпечно деплоїти та перевіряти.

**Architecture:** план розділений на незалежні lanes: production orchestration, refresh queue, Telegram bot UX, web contracts, web visual resilience, backend/scheduler correctness, and final QA. Кожен lane має окремий write scope, regression tests first, і власний commit checkpoint, щоб задачі можна було роздати subagents без конфліктів.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, APScheduler, Redis, aiogram 3, pytest, ruff, Next.js 15, React 19, TypeScript, Vitest, Testing Library, Playwright, Docker Compose, systemd, Prometheus.

---

## Scope And Priorities

Це umbrella plan. Якщо виконувати через subagents, запускати максимум 5 паралельних lanes:

- Lane A: `infra/`, `apps/scheduler/src/main.py`, production preflight.
- Lane B: refresh queue helpers and API/scheduler refresh tests.
- Lane C: bot rendering, URL safety, Telegram message length.
- Lane D: web query/date contracts and tests.
- Lane E: web image fallback and browser UX verification.

Do not refactor deal-detection semantics, pricing thresholds, or Telegram deal copy unless a task explicitly says so. Deal/promo wording and date-dip honesty stay product-governed.

## File Structure

- `infra/systemd/`: keep boot/keepalive ownership only; retire duplicate snapshot timer/service from install path.
- `infra/scripts/production-preflight.sh`: static guard that rejects reintroducing a second snapshot scheduler.
- `apps/scheduler/src/main.py`: single owner of timed scheduler jobs; docs/comments must reflect that.
- `apps/shared/refresh_queue.py`: shared queue constants plus refresh lock key helpers.
- `apps/api/src/services/refresh_queue.py`: user/manual refresh enqueue path.
- `apps/scheduler/src/jobs/snapshot_hot.py`: hot-priority enqueue path.
- `apps/bot/src/infra/telegram_text.py`: shared Telegram parsed-length and safe truncation helpers.
- `apps/bot/src/infra/url_safety.py`: URL allowlist helpers for inline keyboard buttons.
- `apps/bot/src/handlers/deals.py`: `/deals` and `/best` text sizing, edit fallback, URL filtering, runtime/copy alignment.
- `apps/bot/src/handlers/wizard_render.py`: result-button URL filtering; no network or FSM side effects.
- `apps/shared/site_urls.py`: public-site base URL normalization and scheme checks.
- `apps/web/src/lib/search-params.ts`: canonical web search URL contract, date helpers, and serialization.
- `apps/web/src/components/SearchForm.tsx`: uses shared search URL/date helpers.
- `apps/web/src/components/SearchSortControl.tsx`: uses shared search URL helpers.
- `apps/web/src/components/ui/SafeImage.tsx`: shared external-image fallback.
- `apps/web/src/components/HotelCard.tsx` and `apps/web/src/components/HotelPhotoCarousel.tsx`: first consumers of `SafeImage`.

---

### Task 1: Make APScheduler The Only Production Snapshot Owner

**Files:**
- Delete: `infra/systemd/fasttravel-snapshot.service`
- Delete: `infra/systemd/fasttravel-snapshot.timer`
- Modify: `infra/systemd/README.md`
- Modify: `infra/SETUP.md`
- Modify: `infra/scripts/production-preflight.sh`
- Modify: `apps/scheduler/src/main.py`

- [ ] **Step 1: Write the failing preflight guard**

In `infra/scripts/production-preflight.sh`, add this helper near `require_file()`:

```bash
require_absent_file() {
    if [[ -f "$ROOT/$1" ]]; then
        fail "retired file is still present: $1"
    else
        ok "retired file absent: $1"
    fi
}
```

Then add these checks after the existing `require_file infra/scripts/backup-restore-drill.sh` line:

```bash
require_absent_file infra/systemd/fasttravel-snapshot.service
require_absent_file infra/systemd/fasttravel-snapshot.timer
```

Replace the old workflow assertion:

```bash
require_workflow_contains "infra/systemd/fasttravel-snapshot.service" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml exec -T scheduler python -m src\\.jobs\\.snapshot_farvater" "systemd snapshot runs the real Farvater snapshot module"
```

with:

```bash
if rg -n 'fasttravel-snapshot\\.(service|timer)|snapshot_farvater\\.timer' \
    "$ROOT/infra/systemd" "$ROOT/infra/SETUP.md" "$ROOT/infra/systemd/README.md" \
    -g '!infra/scripts/production-preflight.sh' >/tmp/fasttravel-preflight-snapshot-owner.txt; then
    cat /tmp/fasttravel-preflight-snapshot-owner.txt >&2
    fail "systemd snapshot timer/service references found; APScheduler is the only price snapshot owner"
else
    ok "no systemd snapshot owner references found"
fi
```

- [ ] **Step 2: Run preflight and verify it fails before deleting files**

Run:

```bash
bash infra/scripts/production-preflight.sh
```

Expected: FAIL lines for `infra/systemd/fasttravel-snapshot.service` and `infra/systemd/fasttravel-snapshot.timer` being present.

- [ ] **Step 3: Delete the retired snapshot unit files**

Remove:

```bash
rm infra/systemd/fasttravel-snapshot.service infra/systemd/fasttravel-snapshot.timer
```

This is part of the implementation step; do not delete `fasttravel-stack.service`, `fasttravel-keepalive.service`, or `fasttravel-keepalive.timer`.

- [ ] **Step 4: Update systemd docs**

Replace the install block in `infra/systemd/README.md` with:

~~~markdown
# systemd units

Install on the Oracle VM:

```bash
sudo cp infra/systemd/fasttravel-stack.service infra/systemd/fasttravel-keepalive.service infra/systemd/fasttravel-keepalive.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Stack (starts docker-compose at boot)
sudo systemctl enable --now fasttravel-stack.service

# Hourly keepalive (anti-reclamation insert)
sudo systemctl enable --now fasttravel-keepalive.timer
```

Verify timers are scheduled:

```bash
systemctl list-timers --all | grep fasttravel
journalctl -u fasttravel-keepalive.service -n 50 --no-pager
```

Price snapshots are owned by `apps/scheduler/src/main.py` inside the scheduler container. Do not add a systemd timer for `snapshot_farvater`; that creates a second production owner for the same 06:00/18:00 job.

The production compose file is an overlay. All units intentionally call:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ...
```

Do not run `docker-compose.prod.yml` by itself; it does not define standalone images/build contexts for every service.
~~~

- [ ] **Step 5: Update setup install commands**

In `infra/SETUP.md`, replace the systemd copy and enable commands with:

~~~markdown
```bash
scp -i ~/.ssh/fasttravel_oracle \
    infra/systemd/fasttravel-stack.service \
    infra/systemd/fasttravel-keepalive.service \
    infra/systemd/fasttravel-keepalive.timer \
    ubuntu@<public_ip>:/tmp/
```

On the VM:

```bash
sudo mv /tmp/fasttravel-stack.service /tmp/fasttravel-keepalive.service /tmp/fasttravel-keepalive.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fasttravel-stack.service
sudo systemctl enable --now fasttravel-keepalive.timer

systemctl list-timers --all | grep fasttravel
```

`snapshot_farvater` is scheduled inside the `scheduler` container by APScheduler at 06:00 and 18:00 Europe/Kyiv. Do not enable a host-level snapshot timer.
~~~

- [ ] **Step 6: Update scheduler entrypoint comments**

In `apps/scheduler/src/main.py`, update the top docstring schedule paragraph to include:

```python
Price snapshots are owned here, not by host systemd. Production must not
enable a second `snapshot_farvater` timer because duplicate 06:00/18:00
runs create scrape overlap, queue pressure, and lock noise.
```

- [ ] **Step 7: Run validation**

Run:

```bash
bash infra/scripts/production-preflight.sh
```

Expected: the new snapshot-owner guard passes; unrelated warnings are acceptable only if they were already present before this task.

- [ ] **Step 8: Commit**

```bash
git add infra/scripts/production-preflight.sh infra/systemd/README.md infra/SETUP.md apps/scheduler/src/main.py
git rm infra/systemd/fasttravel-snapshot.service infra/systemd/fasttravel-snapshot.timer
git commit -m "fix: make scheduler sole snapshot owner"
```

---

### Task 2: Unify Refresh Lock Semantics Across API And Hot Queue

**Files:**
- Modify: `apps/shared/refresh_queue.py`
- Modify: `apps/api/src/services/refresh_queue.py`
- Modify: `apps/scheduler/src/jobs/snapshot_hot.py`
- Test: `apps/api/tests/test_refresh_rate_limit.py`
- Test: `apps/scheduler/tests/test_snapshot_hot.py`

- [ ] **Step 1: Write failing API test for base lock on custom-night refresh**

In `apps/api/tests/test_refresh_rate_limit.py`, replace the final assertion in `test_refresh_custom_nights_queues_exact_duration_with_separate_lock` with:

```python
    assert first.queued is True
    assert second.queued is False
    assert redis.set_calls == [f"refresh:hotel:{hotel_id}", f"refresh:hotel:{hotel_id}"]

    payloads = [json.loads(item) for item in redis.lists[hotels_router.REFRESH_QUEUE_KEY]]
    assert len(payloads) == 1
    assert "requested_nights" not in payloads[0]
```

Rename the test to:

```python
async def test_refresh_custom_nights_respects_base_hotel_lock(
```

- [ ] **Step 2: Write failing hot-queue test for custom-night lock**

Append to `apps/scheduler/tests/test_snapshot_hot.py`:

```python
@pytest.mark.asyncio
async def test_snapshot_hot_skips_hotels_with_custom_nights_refresh_lock(monkeypatch) -> None:
    redis = _FakeRedis(decode_responses=True)
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")
    await redis.set("refresh:hotel:20:nights:15", "already-refreshing")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({20: "fv20", 30: "fv30"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 1
    payloads = [json.loads(item) for item in await redis.lrange("refresh:queue", 0, -1)]
    assert [item["hotel_id"] for item in payloads] == [30]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd apps/api && PYTHONPATH=.:.. ../api/.venv/bin/python -m pytest tests/test_refresh_rate_limit.py::test_refresh_custom_nights_respects_base_hotel_lock -q
```

Expected: FAIL because custom-night refresh currently queues separately.

Run:

```bash
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/test_snapshot_hot.py::test_snapshot_hot_skips_hotels_with_custom_nights_refresh_lock -q
```

Expected: FAIL because `snapshot_hot` checks only `refresh:hotel:{id}`.

- [ ] **Step 4: Add shared lock helpers**

In `apps/shared/refresh_queue.py`, add below `REFRESH_QUEUE_MAX_LEN = 200`:

```python
REFRESH_LOCK_PREFIX = "refresh:hotel:"


def refresh_lock_key(hotel_id: int, requested_nights: int | None = None) -> str:
    """Return the Redis lock key for one hotel refresh request."""
    base = f"{REFRESH_LOCK_PREFIX}{hotel_id}"
    if requested_nights is None:
        return base
    return f"{base}:nights:{requested_nights}"


def refresh_lock_patterns(hotel_id: int) -> tuple[str, str]:
    """Keys/patterns that indicate this hotel already has refresh work."""
    return (refresh_lock_key(hotel_id), f"{refresh_lock_key(hotel_id)}:nights:*")
```

- [ ] **Step 5: Make API refresh use the base hotel lock**

In `apps/api/src/services/refresh_queue.py`, import `refresh_lock_key`:

```python
from shared.refresh_queue import (
    REFRESH_QUEUE_KEY,
    REFRESH_QUEUE_MAX_LEN,
    RefreshQueueFullError,
    RefreshQueueUnavailableError,
    push_refresh_job_with_cap,
    refresh_lock_key,
)
```

Replace the `cache_key = ...` block with:

```python
    cache_key = refresh_lock_key(hotel_id)
```

Keep `requested_nights` in the queued payload:

```python
    if requested_nights is not None:
        job["requested_nights"] = [requested_nights]
```

This means a hotel can have one active refresh at a time, whether the trigger is user, custom nights, or hot-priority.

- [ ] **Step 6: Make hot queue skip base and custom locks**

In `apps/scheduler/src/jobs/snapshot_hot.py`, import the helpers:

```python
from shared.refresh_queue import (
    REFRESH_QUEUE_KEY,
    RefreshQueueFullError,
    push_refresh_job_with_cap,
    refresh_lock_key,
    refresh_lock_patterns,
)
```

Delete:

```python
REFRESH_LOCK_PREFIX = "refresh:hotel:"
```

Replace the lock-key pipeline block with:

```python
    pipe = redis.pipeline()
    lock_checks: list[tuple[int, str]] = []
    for hid in mapping:
        exact_key, nights_pattern = refresh_lock_patterns(hid)
        pipe.exists(exact_key)
        lock_checks.append((hid, "exact"))
        pipe.keys(nights_pattern)
        lock_checks.append((hid, "nights"))
    lock_results = await pipe.execute()

    locked: set[int] = set()
    for (hid, kind), result in zip(lock_checks, lock_results, strict=False):
        if kind == "exact" and result:
            locked.add(hid)
        if kind == "nights" and result:
            locked.add(hid)
```

For Redis-scale safety, this uses `KEYS` only on `refresh:hotel:{id}:nights:*` for the top-N mapped hotels, not the whole keyspace. If this becomes hot, replace with explicit secondary base lock only and delete the pattern branch.

- [ ] **Step 7: Run targeted tests**

Run:

```bash
cd apps/api && PYTHONPATH=.:.. ../api/.venv/bin/python -m pytest tests/test_refresh_rate_limit.py -q
```

Expected: PASS.

Run:

```bash
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/test_snapshot_hot.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/shared/refresh_queue.py apps/api/src/services/refresh_queue.py apps/scheduler/src/jobs/snapshot_hot.py apps/api/tests/test_refresh_rate_limit.py apps/scheduler/tests/test_snapshot_hot.py
git commit -m "fix: unify hotel refresh lock semantics"
```

---

### Task 3: Harden Bot Message Size, Edit Fallbacks, And Inline URLs

**Files:**
- Create: `apps/bot/src/infra/telegram_text.py`
- Create: `apps/bot/src/infra/url_safety.py`
- Modify: `apps/bot/src/templates/cheap.py`
- Modify: `apps/bot/src/handlers/deals.py`
- Modify: `apps/bot/src/handlers/wizard_render.py`
- Modify: `apps/bot/src/handlers/commands.py`
- Modify: `apps/bot/README.md`
- Test: `apps/bot/tests/test_deals_callbacks.py`
- Test: `apps/bot/tests/test_search_wizard_links.py`
- Test: `apps/bot/tests/test_templates.py`

- [ ] **Step 1: Create tests for Telegram length helper**

Append to `apps/bot/tests/test_templates.py`:

```python
from src.infra.telegram_text import fit_markdown_v2_message, telegram_parsed_len


def test_telegram_parsed_len_ignores_hidden_markdown_link_url() -> None:
    text = r"🛒 [Переглянути →](https://example.com/very/long/path?x=1)"

    assert telegram_parsed_len(text) == len("🛒 Переглянути →".encode("utf-16-le")) // 2


def test_fit_markdown_v2_message_adds_footer_when_truncated() -> None:
    cards = ["Готель " + str(i) + " " + ("x" * 400) for i in range(12)]
    text = fit_markdown_v2_message(
        header="🔥 *Гарячі варіанти*",
        blocks=cards,
        footer="Повний список — /deals",
        separator="\n\n— · — · —\n\n",
        max_parsed_len=900,
    )

    assert telegram_parsed_len(text) <= 900
    assert "Повний список" in text
```

- [ ] **Step 2: Create tests for unsafe URLs**

Append to `apps/bot/tests/test_search_wizard_links.py`:

```python
from src.handlers.wizard_render import result_link_rows


def test_result_link_rows_drop_non_http_operator_links() -> None:
    rows = result_link_rows(
        [
            {
                "deep_link": "javascript:alert(1)",
                "name_uk": "Unsafe Hotel",
                "canonical_slug": "unsafe-hotel",
            }
        ],
        site_base_url="https://fasttravel.example",
    )

    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].url == "https://fasttravel.example/hotels/unsafe-hotel?utm_source=tg_bot&utm_medium=wizard"
```

- [ ] **Step 3: Create `telegram_text.py`**

Add `apps/bot/src/infra/telegram_text.py`:

```python
"""Telegram message-size helpers.

Telegram caps messages at 4096 UTF-16 code units after entity parsing.
These helpers keep bot handlers from sending oversized MarkdownV2 text.
"""

from __future__ import annotations

import re

TELEGRAM_MESSAGE_LIMIT = 4096
DEFAULT_PARSED_LIMIT = 3800

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def telegram_parsed_len(text: str) -> int:
    stripped = _LINK_RE.sub(r"\1", text)
    stripped = stripped.replace("\\", "").replace("*", "")
    return len(stripped.encode("utf-16-le")) // 2


def fit_markdown_v2_message(
    *,
    header: str,
    blocks: list[str],
    footer: str,
    separator: str,
    max_parsed_len: int = DEFAULT_PARSED_LIMIT,
) -> str:
    if not blocks:
        text = f"{header}\n\n{footer}" if footer else header
        return text

    shown: list[str] = []
    footer_cost = telegram_parsed_len(f"\n\n{footer}") if footer else 0
    base_cost = telegram_parsed_len(f"{header}\n\n")
    used = base_cost + footer_cost

    for block in blocks:
        block_cost = telegram_parsed_len(block)
        sep_cost = telegram_parsed_len(separator) if shown else 0
        if shown and used + sep_cost + block_cost > max_parsed_len:
            break
        shown.append(block)
        used += sep_cost + block_cost

    body = separator.join(shown)
    if len(shown) < len(blocks) and footer:
        return f"{header}\n\n{body}\n\n{footer}"
    return f"{header}\n\n{body}"
```

- [ ] **Step 4: Reuse helper in cheap digest**

In `apps/bot/src/templates/cheap.py`, delete the local `telegram_parsed_len` function and `_LINK_RE`, then import:

```python
from src.infra.telegram_text import DEFAULT_PARSED_LIMIT, telegram_parsed_len
```

Replace `_MAX_PARSED_LEN = 3800` with:

```python
_MAX_PARSED_LEN = DEFAULT_PARSED_LIMIT
```

- [ ] **Step 5: Create URL safety helper**

Add `apps/bot/src/infra/url_safety.py`:

```python
"""URL helpers for Telegram inline keyboard buttons."""

from __future__ import annotations

from urllib.parse import urlparse


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def safe_http_url(value: object) -> str | None:
    if not is_http_url(value):
        return None
    return str(value).strip()
```

- [ ] **Step 6: Use safe URLs in wizard buttons**

In `apps/bot/src/handlers/wizard_render.py`, import:

```python
from src.infra.url_safety import safe_http_url
```

Replace:

```python
        deep_link = h.get("deep_link")
```

with:

```python
        deep_link = safe_http_url(h.get("deep_link"))
```

- [ ] **Step 7: Use safe URLs and message fitting in deals**

In `apps/bot/src/handlers/deals.py`, import:

```python
from src.infra.telegram_text import fit_markdown_v2_message
from src.infra.url_safety import safe_http_url
```

In `_build_keyboard`, replace:

```python
        url = deep_link
```

with:

```python
        url = safe_http_url(deep_link)
```

In `_best_keyboard`, make the same replacement for `url = deep_link`.

Replace `_render_page` body with:

```python
def _render_page(deals: list[dict[str, Any]], page: int, total_pages: int) -> str:
    header = f"🔥 *Гарячі варіанти* · сторінка *{page}/{total_pages}*"
    return fit_markdown_v2_message(
        header=header,
        blocks=[render_deal(d) for d in deals],
        footer="Повний список доступний через /deals або сайт\\.",
        separator="\n\n— · — · —\n\n",
    )
```

In `_send_best`, replace:

```python
    body = "\n\n— · — · —\n\n".join(render_deal(d) for d in items)
    text = f"{header}\n\n{body}"
```

with:

```python
    text = fit_markdown_v2_message(
        header=header,
        blocks=[render_deal(d) for d in items],
        footer="Повний список доступний через /deals або сайт\\.",
        separator="\n\n— · — · —\n\n",
    )
```

- [ ] **Step 8: Add edit fallback instead of silent no-op**

In `apps/bot/src/handlers/deals.py`, for both `deals.edit_skip` and `best.edit_skip` blocks, replace only logging with:

```python
            log.warning("deals.edit_failed_fallback_send", error=str(exc))
            await message.answer(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
```

For the `_send_best` catch block, use:

```python
            log.warning("best.edit_failed_fallback_send", error=str(exc))
            await message.answer(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
```

- [ ] **Step 9: Align `/best` copy with runtime**

In `apps/bot/src/handlers/commands.py`, replace:

```python
        "  • /best — ТОП\\-10 варіантів зараз 🏆\n"
```

with:

```python
        "  • /best — ТОП\\-20 варіантів зараз 🏆\n"
```

Update `apps/bot/README.md` command section to say `/best` shows top 20 current deals by discount.

- [ ] **Step 10: Run targeted bot tests**

Run:

```bash
cd apps/bot && PYTHONPATH=.:.. ../scheduler/.venv/bin/python -m pytest tests/test_templates.py tests/test_search_wizard_links.py tests/test_deals_callbacks.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add apps/bot/src/infra/telegram_text.py apps/bot/src/infra/url_safety.py apps/bot/src/templates/cheap.py apps/bot/src/handlers/deals.py apps/bot/src/handlers/wizard_render.py apps/bot/src/handlers/commands.py apps/bot/README.md apps/bot/tests/test_templates.py apps/bot/tests/test_search_wizard_links.py apps/bot/tests/test_deals_callbacks.py
git commit -m "fix: harden telegram message rendering"
```

---

### Task 4: Centralize Web Search URL And Date Contracts

**Files:**
- Modify: `apps/web/src/lib/search-params.ts`
- Modify: `apps/web/src/lib/search-params.test.ts`
- Modify: `apps/web/src/components/SearchForm.tsx`
- Modify: `apps/web/src/components/SearchSortControl.tsx`
- Modify: `apps/web/src/components/SearchSortControl.test.tsx`
- Modify: `apps/web/src/app/search/page.test.tsx`

- [ ] **Step 1: Add failing tests for local date and canonical serialization**

Append to `apps/web/src/lib/search-params.test.ts`:

```ts
import { localTodayIso, serializeSearchParams } from './search-params';

describe('localTodayIso', () => {
  it('uses local calendar parts instead of UTC slicing', () => {
    const value = localTodayIso(new Date(2026, 0, 9, 23, 59, 0));

    expect(value).toBe('2026-01-09');
  });
});

describe('serializeSearchParams', () => {
  it('drops empty values and stale amp params', () => {
    const params = serializeSearchParams({
      country: 'TR',
      checkIn: '',
      nights: '7',
      sort: 'price_desc',
      offset: undefined,
      'amp;offset': '100',
    });

    expect(params.toString()).toBe('country=TR&nights=7&sort=price_desc');
  });
});
```

- [ ] **Step 2: Implement helpers**

In `apps/web/src/lib/search-params.ts`, add:

```ts
export function localTodayIso(now = new Date()): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

type SearchUrlValue = string | number | null | undefined;

export function serializeSearchParams(values: Record<string, SearchUrlValue>): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (key.startsWith('amp;')) continue;
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  return params;
}
```

- [ ] **Step 3: Use local date helper in SearchForm**

In `apps/web/src/components/SearchForm.tsx`, import:

```ts
import { localTodayIso, serializeSearchParams } from '@/lib/search-params';
```

Replace date min calculation:

```tsx
const today = new Date().toISOString().slice(0, 10);
```

with:

```tsx
const today = localTodayIso();
```

Where the component builds a `URLSearchParams` manually on submit, replace the manual empty-value deletion with:

```ts
const params = serializeSearchParams({
  q,
  country,
  check_in: checkIn,
  nights,
  meal_plan: mealPlan,
  price_max: priceMax,
  stars_min: starsMin,
  adults,
  kids: kids.length > 0 ? kids.join(',') : undefined,
  sort,
});
```

Keep existing route push behavior: `router.push(params.toString() ? `/search?${params}` : '/search')`.

- [ ] **Step 4: Use serializer in SearchSortControl**

In `apps/web/src/components/SearchSortControl.tsx`, import:

```ts
import { serializeSearchParams } from '@/lib/search-params';
```

Replace the manual delete logic with:

```ts
const current = Object.fromEntries(searchParams.entries());
delete current.offset;
delete current['amp;offset'];
delete current['amp;sort'];

const params = serializeSearchParams({
  ...current,
  sort: nextSort === DEFAULT_SEARCH_SORT ? undefined : nextSort,
});

router.push(params.toString() ? `${pathname}?${params}` : pathname);
```

- [ ] **Step 5: Run web unit tests**

Run:

```bash
cd apps/web && pnpm test src/lib/search-params.test.ts src/components/SearchForm.test.tsx src/components/SearchSortControl.test.tsx src/app/search/page.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/search-params.ts apps/web/src/lib/search-params.test.ts apps/web/src/components/SearchForm.tsx apps/web/src/components/SearchSortControl.tsx apps/web/src/components/SearchSortControl.test.tsx apps/web/src/app/search/page.test.tsx
git commit -m "refactor: centralize web search url contract"
```

---

### Task 5: Add Safe Image Fallbacks On Main Web Hotel Surfaces

**Files:**
- Create: `apps/web/src/components/ui/SafeImage.tsx`
- Create: `apps/web/src/components/ui/SafeImage.test.tsx`
- Modify: `apps/web/src/components/ui/index.ts`
- Modify: `apps/web/src/components/HotelCard.tsx`
- Modify: `apps/web/src/components/HotelCard.test.tsx`
- Modify: `apps/web/src/components/HotelPhotoCarousel.tsx`
- Modify: `apps/web/src/components/HotelPhotoCarousel.test.tsx`

- [ ] **Step 1: Write SafeImage test**

Create `apps/web/src/components/ui/SafeImage.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { SafeImage } from './SafeImage';

describe('SafeImage', () => {
  it('renders fallback when src is missing', () => {
    render(<SafeImage src={null} alt="Фото готелю" className="h-10 w-10" />);

    expect(screen.getByText('Фото недоступне')).toBeInTheDocument();
  });

  it('renders fallback after image load error', () => {
    render(<SafeImage src="https://cdn.example/broken.jpg" alt="Фото готелю" className="h-10 w-10" />);

    fireEvent.error(screen.getByRole('img', { name: 'Фото готелю' }));

    expect(screen.getByText('Фото недоступне')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement SafeImage**

Create `apps/web/src/components/ui/SafeImage.tsx`:

```tsx
'use client';

import { ImageOff } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';

interface SafeImageProps {
  src: string | null | undefined;
  alt: string;
  className?: string;
  imgClassName?: string;
}

export function SafeImage({ src, alt, className, imgClassName }: SafeImageProps) {
  const [failed, setFailed] = useState(false);
  const usableSrc = typeof src === 'string' && src.trim().length > 0 && !failed ? src : null;

  if (!usableSrc) {
    return (
      <div
        className={cn(
          'flex items-center justify-center bg-slate-100 text-slate-500',
          className,
        )}
      >
        <div className="flex flex-col items-center gap-2 text-xs font-medium">
          <ImageOff aria-hidden="true" className="h-5 w-5" />
          <span>Фото недоступне</span>
        </div>
      </div>
    );
  }

  return (
    <img
      src={usableSrc}
      alt={alt}
      className={cn('h-full w-full object-cover', imgClassName ?? className)}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}
```

- [ ] **Step 3: Export SafeImage**

In `apps/web/src/components/ui/index.ts`, add:

```ts
export { SafeImage } from './SafeImage';
```

- [ ] **Step 4: Use SafeImage in HotelCard**

In `apps/web/src/components/HotelCard.tsx`, import:

```ts
import { SafeImage } from '@/components/ui';
```

Replace the current photo/emoji placeholder branch with:

```tsx
<SafeImage
  src={photoUrl}
  alt={`Фото готелю ${hotel.name_uk}`}
  className="h-44 w-full transition-transform duration-300 group-hover:scale-105"
/>
```

Ensure the card hover root has `group` in its class list:

```tsx
className="group overflow-hidden"
```

- [ ] **Step 5: Use SafeImage in HotelPhotoCarousel**

In `apps/web/src/components/HotelPhotoCarousel.tsx`, import `SafeImage` and render the main image with:

```tsx
<SafeImage
  src={activePhoto.url}
  alt={`Фото ${activeIndex + 1} з ${photos.length}`}
  className="aspect-[16/10] w-full rounded-md"
/>
```

Keep thumbnail buttons as native `img` only if the test still confirms main-image fallback. If thumbnails also break visually, convert thumbnails to `SafeImage` with stable square dimensions.

- [ ] **Step 6: Run component tests**

Run:

```bash
cd apps/web && pnpm test src/components/ui/SafeImage.test.tsx src/components/HotelCard.test.tsx src/components/HotelPhotoCarousel.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/components/ui/SafeImage.tsx apps/web/src/components/ui/SafeImage.test.tsx apps/web/src/components/ui/index.ts apps/web/src/components/HotelCard.tsx apps/web/src/components/HotelCard.test.tsx apps/web/src/components/HotelPhotoCarousel.tsx apps/web/src/components/HotelPhotoCarousel.test.tsx
git commit -m "feat: add resilient hotel image fallback"
```

---

### Task 6: Lock Backend/Scheduler Regression Tests Around Deal And Alert Pipelines

**Files:**
- Modify: `apps/scheduler/src/jobs/notify_subscribers.py`
- Test: `apps/scheduler/tests/test_notify_subscribers.py`
- Test: `apps/api/tests/test_deals.py`
- Test: `apps/scheduler/tests/test_deal_safety_sql.py`

- [ ] **Step 1: Add notify ledger failure regression test**

In `apps/scheduler/tests/test_notify_subscribers.py`, add a test that stubs a successful Telegram send and a failing ledger commit. Use the existing fake session/messenger patterns in this file; the assertion contract is:

```python
assert result.sent == 1
assert result.failed == 0
assert "notified_ledger_failed" in caplog.text
```

If this file exposes a dict result instead of a dataclass, assert:

```python
assert stats["sent"] == 1
assert stats["failed"] == 0
```

- [ ] **Step 2: Refactor notify ledger write into its own try block**

In `apps/scheduler/src/jobs/notify_subscribers.py`, locate the block that sends Telegram and writes `_MARK_NOTIFIED`. Keep the send try/except around only the send. After a successful send, write the ledger in a separate block:

```python
            sent += 1
            try:
                await db.execute(
                    _MARK_NOTIFIED,
                    {"filter_id": row.filter_id, "deal_id": row.deal_id},
                )
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                log.warning(
                    "notify_subscribers.notified_ledger_failed",
                    filter_id=row.filter_id,
                    deal_id=row.deal_id,
                    error=str(exc),
                )
```

Do not increment `failed` in this ledger-failure branch; the user already received the message.

- [ ] **Step 3: Ensure deals pagination deterministic test exists**

In `apps/api/tests/test_deals.py`, add or update a test that inserts same-`detected_at` deals and checks stable page order:

```python
async def test_list_deals_uses_unique_tie_break_for_offset_pages(client, db_session) -> None:
    # Insert 6 public deals with identical detected_at and discount_pct.
    # Fetch limit=3 offset=0 and limit=3 offset=3.
    # Assert the combined ids have length 6 and no duplicates.
```

Implementation must use the repository's existing fixture insertion helpers from `test_deals.py`; do not invent a second DB fixture system.

- [ ] **Step 4: Run targeted backend/scheduler tests**

Run:

```bash
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/test_notify_subscribers.py tests/test_deal_safety_sql.py -q
```

Expected: PASS.

Run:

```bash
cd apps/api && PYTHONPATH=.:.. ../api/.venv/bin/python -m pytest tests/test_deals.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/scheduler/src/jobs/notify_subscribers.py apps/scheduler/tests/test_notify_subscribers.py apps/api/tests/test_deals.py apps/scheduler/tests/test_deal_safety_sql.py
git commit -m "test: lock deal and alert pipeline regressions"
```

---

### Task 7: Final Project QA Matrix And Browser UX Verification

**Files:**
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/IMPROVEMENT_BACKLOG.md`
- No code changes outside docs unless a verification failure identifies a concrete regression.

- [ ] **Step 1: Update operations verification checklist**

Append this section to `docs/OPERATIONS.md`:

```markdown
## Full Local Verification Matrix

Use after cross-service changes:

```bash
cd apps/web && pnpm test && pnpm typecheck && pnpm lint && pnpm build
cd apps/web && pnpm test:e2e

cd apps/api && PYTHONPATH=.:.. ../api/.venv/bin/python -m pytest tests/ -q
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/ -q
cd apps/bot && PYTHONPATH=.:.. ../scheduler/.venv/bin/python -m pytest tests/ -q

cd apps/api && ../api/.venv/bin/ruff check src tests
cd apps/scheduler && ../api/.venv/bin/ruff check src tests
cd apps/bot && ../api/.venv/bin/ruff check src tests

bash infra/scripts/production-preflight.sh
git diff --check
```

Browser UX smoke routes:

- `/`
- `/search?country=TR&offset=48`
- `/deals`
- `/cheap`
- `/telegram`
- `/about`
- one seeded `/hotels/{slug}` page

For `/search?country=TR&offset=48`, change sort and verify `offset` is removed from the URL. For hotel detail, switch nights, trigger refresh, and verify the UI remains stable on mobile and desktop.
```

- [ ] **Step 2: Mark superseded backlog items**

In `docs/IMPROVEMENT_BACKLOG.md`, add a short status note below the title:

```markdown
> Status note, 2026-06-08: several P0/P1 bot and web items have since been fixed in code. Treat this backlog as historical evidence; use `docs/superpowers/plans/2026-06-08-fasttravel-full-project-hardening.md` for the current execution sequence.
```

- [ ] **Step 3: Run full verification**

Run:

```bash
cd apps/web && pnpm test && pnpm typecheck && pnpm lint && pnpm build
```

Expected: all pass.

Run:

```bash
cd apps/web && pnpm test:e2e
```

Expected: all Playwright smoke tests pass.

Run:

```bash
cd apps/api && PYTHONPATH=.:.. ../api/.venv/bin/python -m pytest tests/ -q
```

Expected: all API tests pass.

Run:

```bash
cd apps/scheduler && PYTHONPATH=.:.. .venv/bin/python -m pytest tests/ -q
```

Expected: all scheduler tests pass.

Run:

```bash
cd apps/bot && PYTHONPATH=.:.. ../scheduler/.venv/bin/python -m pytest tests/ -q
```

Expected: all bot tests pass.

Run:

```bash
for svc in api scheduler bot; do
  (cd apps/$svc && ../api/.venv/bin/ruff check src tests)
done
```

Expected: ruff passes for all Python services.

Run:

```bash
bash infra/scripts/production-preflight.sh
git diff --check
```

Expected: preflight passes and no whitespace errors.

- [ ] **Step 4: Browser verification**

Start local services:

```bash
docker compose up -d postgres redis
cd apps/web && NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
```

Use Playwright or the available browser surface to verify:

```ts
await page.goto('http://127.0.0.1:3000/search?country=TR&offset=48');
await page.getByLabel(/Сортування результатів/).selectOption('price_desc');
await expect(page).toHaveURL(/sort=price_desc/);
await expect(page).not.toHaveURL(/offset=/);

await page.setViewportSize({ width: 390, height: 844 });
await page.goto('http://127.0.0.1:3000/deals');
await expect(page.getByRole('link', { name: /Деталі пропозиції/ }).first()).toBeVisible();
```

If `next build` ran while `next dev` was active and the browser shows chunk/client-manifest errors, stop dev, remove `.next`, restart dev, and rerun the browser checks.

- [ ] **Step 5: Commit docs and QA evidence**

```bash
git add docs/OPERATIONS.md docs/IMPROVEMENT_BACKLOG.md
git commit -m "docs: add full verification matrix"
```

---

## Execution Order

1. Task 1 first. It removes the production double-scheduler risk and changes infra docs/preflight.
2. Task 2 second. It changes shared refresh semantics used by API and scheduler.
3. Tasks 3, 4, and 5 can run in parallel after Task 2 because write scopes are disjoint.
4. Task 6 after Task 2 because it depends on stable scheduler/API behavior.
5. Task 7 last. It is the final evidence pass and docs checkpoint.

## Stop Conditions

- Stop immediately and investigate if any task changes deal selection thresholds, `DATE_DIP_POLICY`, affiliate link `rel` contracts, or Telegram date-dip copy without an explicit task step.
- Stop and split work if a task requires a database migration not listed here.
- Stop and report if production preflight reveals unrelated deploy-blocking failures that cannot be fixed within the task's file scope.

## Self-Review

- Spec coverage: project logic, code structure, scheduler/backend logic, web UX, bot UX, testing, and operations are covered by Tasks 1-7.
- Placeholder scan: no open-ended implementation markers remain; every task has file paths, commands, and expected results.
- Type consistency: refresh helper names are `refresh_lock_key` and `refresh_lock_patterns`; web helper names are `localTodayIso` and `serializeSearchParams`; Telegram helper names are `telegram_parsed_len` and `fit_markdown_v2_message`.
