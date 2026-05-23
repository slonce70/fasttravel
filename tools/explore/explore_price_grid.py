"""Look at the small price-grid in the upper-right of the farvater hotel
page. Dump its HTML, capture XHRs fired when a cell is clicked."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "out"
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
            key = (req.method, url.split("?")[0], body[:100])
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
                "method": req.method, "url": url, "status": resp.status,
                "request_body": body, "content_type": ctype,
                "preview": (text or "")[:3500],
            })
            print(f"  [{resp.status}] {req.method:5} {url[:170]}", flush=True)

        page.on("response", on_resp)

        new_pages: list = []
        ctx.on("page", lambda p: new_pages.append(p))

        await page.goto(HOTEL_URL, wait_until="networkidle", timeout=90_000)
        await page.wait_for_timeout(10_000)

        # Look at the area in upper-right where the price grid lives
        # (visible in screenshot around x=900..1300, y=180..380).
        # Just dump the FULL hotel page HTML for the right column and
        # search for anything that looks like a buy/select control on a
        # specific date+price tuple.
        grid_html = await page.evaluate("""
        () => {
          // Try a few selectors that ittour-style sites use for price tables
          const candidates = [
            '.calendar', '[class*="calendar"]',
            '[class*="price-table"]', '[class*="priceTable"]',
            '[class*="hotel-prices"]', '[class*="lowprice"]',
            'table',
          ];
          for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el) {
              const r = el.getBoundingClientRect();
              if (r.width > 100 && r.height > 100) {
                return { sel, html: el.outerHTML.slice(0, 10000), rect: { x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0 } };
              }
            }
          }
          return null;
        }
        """)
        if grid_html:
            Path(OUT / "price_grid.html").write_text(grid_html['html'])
            print(f"  grid found via «{grid_html['sel']}» rect={grid_html['rect']}", flush=True)
            print(f"  saved {len(grid_html['html'])} bytes → out/price_grid.html", flush=True)
        else:
            print("  ! no grid via standard selectors. Dumping full HTML.", flush=True)
            full = await page.content()
            Path(OUT / "full_hotel_page.html").write_text(full)
            print(f"  saved {len(full)} bytes → out/full_hotel_page.html", flush=True)

        # Also enumerate ALL elements that have a price string in their
        # text and ARE clickable (a or button or has cursor:pointer)
        clickables = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('*'));
          const out = [];
          for (const el of all) {
            const t = (el.innerText || '').trim();
            if (!t) continue;
            // Looks like a price number
            const hasPrice = /\\d+\\s?\\d{3,}/.test(t) && t.length < 200;
            if (!hasPrice) continue;
            const tag = el.tagName.toLowerCase();
            const cs = getComputedStyle(el);
            const clickable = tag === 'a' || tag === 'button'
                              || cs.cursor === 'pointer'
                              || el.onclick !== null;
            if (!clickable) continue;
            const r = el.getBoundingClientRect();
            if (r.width < 20 || r.height < 10) continue;
            out.push({
              tag, text: t.replace(/\\s+/g, ' ').slice(0, 120),
              href: el.href || null,
              cls: (el.className||'').toString().slice(0, 120),
              rect: { x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0 },
            });
          }
          return out.slice(0, 20);
        }
        """)
        print(f"\n→ {len(clickables)} clickable elements with price text:", flush=True)
        for c in clickables[:10]:
            print(f"  {c['tag']:6} pos=({c['rect']['x']:4},{c['rect']['y']:4}) text='{c['text'][:80]}' href={c['href']!r}", flush=True)
        Path(OUT / "price_clickables.json").write_text(
            json.dumps(clickables, indent=2, ensure_ascii=False)
        )

        # Click the first clickable that has a price
        if clickables:
            print(f"\n→ Clicking first price-clickable", flush=True)
            try:
                await page.evaluate("""
                () => {
                  const all = Array.from(document.querySelectorAll('*'));
                  for (const el of all) {
                    const t = (el.innerText || '').trim();
                    if (!/\\d+\\s?\\d{3,}/.test(t) || t.length >= 200) continue;
                    const tag = el.tagName.toLowerCase();
                    const cs = getComputedStyle(el);
                    const clickable = tag === 'a' || tag === 'button'
                                      || cs.cursor === 'pointer' || el.onclick !== null;
                    if (!clickable) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 10) continue;
                    el.scrollIntoView({ block: 'center' });
                    el.click();
                    return el.innerText.trim().slice(0, 80);
                  }
                }
                """)
                await page.wait_for_timeout(10_000)
            except Exception as exc:
                print(f"  ! click error: {exc}", flush=True)

            print(f"  URL = {page.url}", flush=True)
            for i, np in enumerate(new_pages):
                try:
                    print(f"  new tab[{i}] = {np.url}", flush=True)
                except Exception:
                    pass

        await page.screenshot(path=str(OUT / "after_price_click.png"), full_page=True)

        # Now look for anything that says "Купити" / "Обрати" on the *current* page state
        post_buy = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('a, button, [role="button"]'));
          return all.filter(el => {
            const t = (el.innerText || '').trim();
            return /купити|замовити|обрати|оформити|book|buy/i.test(t)
                   && !/обрати дату/i.test(t)
                   && el.getBoundingClientRect().width > 30;
          }).slice(0, 10).map(el => ({
            tag: el.tagName,
            text: el.innerText.trim().slice(0, 100),
            href: el.href || null,
            target: el.target || null,
            parentText: (el.parentElement?.innerText || '').replace(/\\s+/g, ' ').slice(0, 200),
          }));
        }
        """)
        print(f"\n→ {len(post_buy)} buy candidates AFTER price-click:", flush=True)
        for c in post_buy:
            print(f"  {c['tag']:6} '{c['text']}' href={c['href']!r}", flush=True)
            if c['parentText']:
                print(f"        ctx: {c['parentText'][:160]}", flush=True)
        Path(OUT / "post_buy_candidates.json").write_text(
            json.dumps(post_buy, indent=2, ensure_ascii=False)
        )

        await b.close()

    Path(OUT / "price_grid_xhr.json").write_text(
        json.dumps(captured, indent=2, ensure_ascii=False)
    )
    print(f"\n✅ {len(captured)} XHRs", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
