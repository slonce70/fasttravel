"""Discover farvater's *real* buy flow.

We currently send users to /uk/hotel/{slug}?systemKey=...  — the hotel
page with a preselected offer. The user wants the click to land
*directly* on the operator-specific buy/checkout/booking page (like
farvater's own offers list does).

This script:
  1. Opens a real hotel page on farvater.
  2. Waits for the prices/offers panel to load (XHR captured).
  3. Inspects the buttons farvater renders next to each operator's price.
  4. Clicks one of them and records: target URL, opened tab, any XHR.
  5. Writes everything to out/buy_flow.json + screenshots before/after.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

HOTEL_URL = "https://farvater.travel/uk/hotel/eg/pickalbatros-vita-resort-portofino/"


def _interesting(url: str, rt: str) -> bool:
    if rt not in ("xhr", "fetch", "document"):
        return False
    h = urlsplit(url).netloc
    if "farvater" not in h and "ittour" not in h:
        return False
    p = urlsplit(url).path
    junk = ("/cdn-cgi/", "/_next/", "/static/", "/favicon", "/sw.js",
            "/partners/statistic_add", "/guest/log-data",
            "/guest/get-base-info", "/u/isLogin", "/u/crm/",
            "/agency-partner/", "/health-srv/", "/autocomplete/")
    return not any(j in p for j in junk)


async def run() -> None:
    captured: list[dict] = []
    seen: set = set()

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/121 Safari/537.36"),
            viewport={"width": 1440, "height": 1000},
            locale="uk-UA", timezone_id="Europe/Kyiv",
        )
        page = await ctx.new_page()

        async def on_resp(resp):
            req = resp.request
            url, rt = req.url, req.resource_type
            if not _interesting(url, rt):
                return
            body = (req.post_data or "")[:1500]
            key = (req.method, url.split("?")[0], body[:200])
            if key in seen:
                return
            seen.add(key)
            text = None
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" in ctype or "asmx" in url or "text" in ctype:
                try:
                    bb = await resp.body()
                    if bb and len(bb) < 1_500_000:
                        text = bb.decode("utf-8", errors="replace")
                except Exception:
                    pass
            captured.append({
                "method": req.method,
                "url": url,
                "status": resp.status,
                "request_body": body,
                "content_type": ctype,
                "preview": (text or "")[:4000],
            })
            print(f"  [{resp.status}] {req.method:5} {url[:170]}", flush=True)

        page.on("response", on_resp)

        # ── Step 1: open hotel page, wait for prices to render
        print(f"\n→ Opening {HOTEL_URL}", flush=True)
        try:
            await page.goto(HOTEL_URL, wait_until="networkidle", timeout=90_000)
        except Exception as exc:
            print(f"  ! goto slow: {exc}", flush=True)
        await page.wait_for_timeout(12_000)  # heavy JS loads offer list

        # Scroll so the calendar/offers area renders
        await page.evaluate("window.scrollTo(0, 1200)")
        await page.wait_for_timeout(4_000)
        await page.evaluate("window.scrollTo(0, 2500)")
        await page.wait_for_timeout(4_000)

        await page.screenshot(path=str(OUT / "buy_before_click.png"), full_page=True)

        # ── Step 2: find "Купити"-like buttons / offer rows
        offer_candidates = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('a, button, [role="button"]'));
          const candidates = all.filter(el => {
            const t = (el.innerText || '').trim();
            return /купити|замовити|обрати|обра́ти|перейти|book|обрать/i.test(t)
                   && el.getBoundingClientRect().width > 30;
          });
          return candidates.slice(0, 12).map((el, i) => ({
            i,
            tag: el.tagName,
            text: (el.innerText || '').trim().slice(0, 80),
            href: el.href || null,
            onclick: el.getAttribute('onclick'),
            dataKeys: Array.from(el.attributes)
              .filter(a => a.name.startsWith('data-'))
              .map(a => `${a.name}="${a.value.slice(0, 80)}"`).slice(0, 8),
            rect: (() => {
              const r = el.getBoundingClientRect();
              return { x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0 };
            })(),
            parentText: (el.closest('[class*="offer"], [class*="tour"], [class*="price"], [class*="item"]')
              ?.innerText || '').replace(/\\s+/g, ' ').slice(0, 220),
          }));
        }
        """)
        Path(OUT / "buy_candidates.json").write_text(
            json.dumps(offer_candidates, indent=2, ensure_ascii=False)
        )
        print(f"\nFound {len(offer_candidates)} buy-like candidates:", flush=True)
        for c in offer_candidates[:5]:
            print(f"  [{c['i']}] {c['tag']:6} '{c['text']}' href={c['href']!r}", flush=True)
            if c['parentText']:
                print(f"        ctx: {c['parentText'][:140]}", flush=True)

        # ── Step 3: try clicking the first buy/обрати candidate
        if not offer_candidates:
            print("  ! no buy candidates found", flush=True)
            await b.close()
            return

        target_idx = 0
        # Prefer one whose parent has a price string (₴ or $ or "грн")
        for i, c in enumerate(offer_candidates):
            if any(s in c['parentText'] for s in ('₴', 'грн', '$ ', 'USD', 'EUR')):
                target_idx = i
                break

        cand = offer_candidates[target_idx]
        print(f"\n→ Clicking [{target_idx}] '{cand['text']}'", flush=True)

        # Capture new tabs / popups
        new_pages = []
        ctx.on("page", lambda p: new_pages.append(p))

        try:
            # Use JS click so we get any popup; await navigation/popup
            await page.evaluate(f"""
            () => {{
              const all = Array.from(document.querySelectorAll('a, button, [role="button"]'));
              const cand = all.filter(el => {{
                const t = (el.innerText || '').trim();
                return /купити|замовити|обрати|обра́ти|перейти|book|обрать/i.test(t)
                       && el.getBoundingClientRect().width > 30;
              }})[{target_idx}];
              if (cand) cand.click();
            }}
            """)
            await page.wait_for_timeout(8_000)
        except Exception as exc:
            print(f"  ! click error: {exc}", flush=True)

        print(f"  page.url AFTER click = {page.url}", flush=True)
        for i, np in enumerate(new_pages):
            try:
                u = np.url
                print(f"  new tab [{i}] = {u}", flush=True)
            except Exception:
                pass

        await page.screenshot(path=str(OUT / "buy_after_click.png"), full_page=False)

        await b.close()

    Path(OUT / "buy_flow_xhr.json").write_text(
        json.dumps(captured, indent=2, ensure_ascii=False)
    )
    print(f"\n✅ Captured {len(captured)} XHRs → out/buy_flow_xhr.json", flush=True)
    print("Screenshots: out/buy_before_click.png, out/buy_after_click.png", flush=True)
    print("Candidate inventory: out/buy_candidates.json", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
