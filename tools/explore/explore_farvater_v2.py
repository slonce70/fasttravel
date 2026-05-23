"""farvater.travel explorer — v2.

v1 only captured autocomplete + analytics. v2 actually triggers a search and
opens a hotel detail page, which is where the price-calendar XHR fires.

Approach:
1. Visit homepage.
2. Snapshot the search form's DOM to find inputs (country, dateFrom, dateTo,
   nights, the submit button).
3. Fill the form programmatically — choose Turkey + 2 weeks out + 7 nights.
4. Submit. Wait for navigation to the results page.
5. On the results page, dump the first hotel detail link.
6. Open the hotel detail page. Wait for full network idle.
7. Save ALL captured XHR + responses for analysis.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, Response

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)


def _is_interesting(url: str, rtype: str) -> bool:
    if rtype not in ("xhr", "fetch", "document"):
        return False
    host = urlsplit(url).netloc.lower()
    if not (host.endswith("farvater.travel") or host.endswith("farvater.ua")
            or "ittour" in host or "tat.ua" in host):
        return False
    path = urlsplit(url).path
    junk = ("/analytics", "/gtag", "/gtm", "/_next/static/",
            "/sw.js", "/favicon", "/__/firebase", "/sockjs-node",
            "/cdn-cgi/", "/partners/statistic_add", "/guest/log-data",
            "/guest/get-base-info", "/u/crm/requestcode", "/u/isLogin",
            "/agency-partner/isExist", "/health-srv/fix-404")
    if any(j in path for j in junk):
        return False
    return True


async def run() -> None:
    captured: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="uk-UA",
            timezone_id="Europe/Kyiv",
        )
        page = await ctx.new_page()

        async def on_response(resp: Response) -> None:
            req = resp.request
            url, rtype = req.url, req.resource_type
            if not _is_interesting(url, rtype):
                return
            body = (req.post_data or "")[:3000]
            key = (req.method, url.split("?")[0], body[:200])
            if key in seen_keys:
                return
            seen_keys.add(key)

            response_text: str | None = None
            response_json = None
            ctype = (resp.headers or {}).get("content-type", "")
            if "application/json" in ctype or "asmx" in url or "text" in ctype:
                try:
                    bb = await resp.body()
                    if bb and len(bb) < 2_000_000:
                        response_text = bb.decode("utf-8", errors="replace")
                        try:
                            response_json = json.loads(response_text)
                        except Exception:
                            response_json = None
                except Exception:
                    pass

            captured.append({
                "method": req.method, "url": url, "resource_type": rtype,
                "status": resp.status,
                "request_headers": {k.lower(): v for k, v in (req.headers or {}).items()
                                     if k.lower() in (
                                         "content-type", "accept", "x-requested-with",
                                         "authorization", "cookie", "x-csrf-token",
                                         "referer",
                                     )},
                "request_body": body,
                "response_content_type": ctype,
                "response_text_preview": (response_text or "")[:8000],
                "response_is_json": response_json is not None,
                "response_json_keys": (
                    list(response_json.keys())[:30] if isinstance(response_json, dict) else None
                ),
            })
            print(f"  [{resp.status}] {req.method} {url[:170]}", flush=True)

        page.on("response", on_response)

        # 1) Homepage.
        print("\n→ Homepage", flush=True)
        await page.goto("https://farvater.travel/uk/", wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(3000)

        # 2) Inspect the search form.
        print("\n→ Inspecting search form…", flush=True)
        form_summary = await page.evaluate("""
        () => {
          const inputs = Array.from(document.querySelectorAll('input,select,button'));
          return inputs.slice(0, 30).map(el => ({
            tag: el.tagName,
            type: el.type || '',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            text: (el.innerText||'').slice(0, 80),
            classes: (el.className||'').slice(0, 120),
          }));
        }
        """)
        Path(OUT_DIR / "form_dump.json").write_text(
            json.dumps(form_summary, indent=2, ensure_ascii=False)
        )
        print(f"  saved form_dump.json ({len(form_summary)} elements)", flush=True)

        # 3) Try to find and click the country selector / search button.
        # Many ittour-style widgets have a "Шукати" / "Знайти" button — click it.
        try:
            clicked = await page.evaluate("""
            () => {
              const btns = Array.from(document.querySelectorAll('button, a, .button, [role="button"]'));
              const target = btns.find(b => /шука(ти|й)|знайти|search/i.test(b.innerText||''));
              if (target) { target.click(); return target.innerText.slice(0, 60); }
              return null;
            }
            """)
            print(f"  clicked search-like button: {clicked!r}", flush=True)
        except Exception as exc:
            print(f"  ! click failed: {exc}", flush=True)

        await page.wait_for_timeout(6000)

        # 4) See current URL — did we navigate?
        print(f"  current URL after search click: {page.url}", flush=True)

        # 5) Look at the page for hotel links.
        hotel_hrefs = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('a[href]'));
          const hotels = all
            .map(a => a.href)
            .filter(h => /\\/hotel(s)?\\//.test(h) && !/hotelscatalog/.test(h))
            .filter((h, i, arr) => arr.indexOf(h) === i)
            .slice(0, 10);
          return hotels;
        }
        """)
        print(f"  hotel links found: {len(hotel_hrefs)}", flush=True)
        for h in hotel_hrefs[:5]:
            print(f"    - {h}", flush=True)

        # 6) Open the first real hotel page.
        target_hotel = None
        for h in hotel_hrefs:
            if "/hotelscatalog/" not in h:
                target_hotel = h
                break
        if not target_hotel:
            # Fallback: probe a known ittour-style hotel slug
            # (we'll learn the real URL pattern from search results, but try a guess)
            print("  no hotel link found — visiting catalog to find one", flush=True)
            await page.goto("https://farvater.travel/uk/hotelscatalog/?strana=4",
                            wait_until="networkidle", timeout=60_000)
            await page.wait_for_timeout(4000)
            hotel_hrefs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
              .map(a => a.href)
              .filter(h => /\\/hotelscatalog\\/[^?]+\\//.test(h))
              .filter((h, i, arr) => arr.indexOf(h) === i)
              .slice(0, 10);
            """)
            print(f"  catalog hotel links: {len(hotel_hrefs)}", flush=True)
            for h in hotel_hrefs[:5]:
                print(f"    - {h}", flush=True)
            if hotel_hrefs:
                target_hotel = hotel_hrefs[0]

        if target_hotel:
            print(f"\n→ Opening hotel: {target_hotel}", flush=True)
            try:
                await page.goto(target_hotel, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(8000)
            except Exception as exc:
                print(f"  ! hotel goto failed: {exc}", flush=True)

        await browser.close()

    out = OUT_DIR / "xhr_capture_v2.json"
    out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
    print(f"\n✅ Captured {len(captured)} requests → {out}", flush=True)

    # Path summary.
    print("\n=== ENDPOINTS ===", flush=True)
    by_path: dict[str, list[dict]] = {}
    for c in captured:
        by_path.setdefault(urlsplit(c["url"]).path, []).append(c)
    for p, items in sorted(by_path.items(), key=lambda x: -len(x[1])):
        methods = sorted({i["method"] for i in items})
        statuses = sorted({i["status"] for i in items})
        json_n = sum(1 for i in items if i["response_is_json"])
        print(f"  {','.join(methods):8} {p[:100]:100} count={len(items):2} status={statuses} json={json_n}")


if __name__ == "__main__":
    asyncio.run(run())
