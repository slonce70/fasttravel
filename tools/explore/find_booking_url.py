"""Discover how farvater's own 'Купити'/'Замовити' button works.

Hypothesis: the systemKey we already have should map to a specific URL
that opens the booking flow directly (not just the hotel page). We let
Playwright record the click and report the resulting URL + any XHR fired.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)


async def run() -> None:
    captured: list[dict] = []
    nav_events: list[str] = []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="uk-UA", timezone_id="Europe/Kyiv",
        )
        page = await ctx.new_page()

        async def on_resp(resp):
            req = resp.request
            url = req.url
            host = urlsplit(url).netloc
            if "farvater" not in host:
                return
            path = urlsplit(url).path
            if any(j in path for j in ("/static/", "/_next/", "/favicon", "/cdn-cgi/",
                                        "/partners/statistic", "/u/isLogin", "/u/crm/",
                                        "/agency-partner/", "/health-srv/", "/guest/")):
                return
            body = (req.post_data or "")[:1500]
            jsn = None
            try:
                if "json" in (resp.headers or {}).get("content-type", ""):
                    raw = await resp.body()
                    if raw and len(raw) < 200_000:
                        try:
                            jsn = json.loads(raw.decode("utf-8", errors="replace"))
                        except Exception:
                            pass
            except Exception:
                pass
            captured.append({
                "method": req.method, "url": url, "status": resp.status,
                "body": body,
                "json_keys": list(jsn.keys())[:20] if isinstance(jsn, dict) else None,
                "json_preview": json.dumps(jsn, ensure_ascii=False)[:1500]
                if jsn is not None else None,
            })
            print(f"  [{resp.status}] {req.method} {url[:170]}", flush=True)

        page.on("response", on_resp)
        page.on("framenavigated", lambda f: nav_events.append(f.url))

        url = ("https://farvater.travel/uk/hotel/eg/pickalbatros-vita-resort-portofino"
               "?systemKey=2m3140873914944168935c25")
        print(f"\n→ Opening {url}\n", flush=True)
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            print(f"  ! load slow: {exc}", flush=True)

        await page.wait_for_timeout(10_000)

        # Find buttons that look like "buy/order/book"
        buy_candidates = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('a,button,[role="button"]'));
          return all
            .filter(el => /купити|замовити|забронювати|оформити|book/i.test(el.textContent||''))
            .slice(0, 8)
            .map((el, i) => ({
              i, tag: el.tagName,
              text: (el.textContent||'').trim().slice(0,80),
              href: el.href || null,
              onclick: el.getAttribute('onclick'),
              dataAttrs: Array.from(el.attributes)
                .filter(a => a.name.startsWith('data-'))
                .map(a => `${a.name}=${a.value.slice(0,80)}`).slice(0,6),
              rect: (() => { const r = el.getBoundingClientRect(); return { x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0 }; })(),
            }));
        }
        """)
        Path(OUT_DIR / "buy_candidates.json").write_text(
            json.dumps(buy_candidates, indent=2, ensure_ascii=False)
        )
        print(f"\n=== buy candidates ===", flush=True)
        for c in buy_candidates:
            print(f"  [{c['i']}] {c['tag']:6} {c['text'][:50]:50} href={c['href']!s:60}",
                  flush=True)
            if c["dataAttrs"]:
                print(f"        data: {c['dataAttrs']}", flush=True)

        # Click the most promising one and see what fires.
        if buy_candidates:
            target_idx = 0
            print(f"\n→ Clicking [{target_idx}] '{buy_candidates[target_idx]['text']}'",
                  flush=True)
            try:
                # Need a fresh element handle — DOM may have updated.
                await page.evaluate(f"""
                () => {{
                  const all = Array.from(document.querySelectorAll('a,button,[role="button"]'));
                  const targets = all.filter(el => /купити|замовити|забронювати|оформити|book/i.test(el.textContent||''));
                  if (targets[{target_idx}]) targets[{target_idx}].click();
                }}
                """)
                await page.wait_for_timeout(8_000)
                print(f"  after click → url is: {page.url}", flush=True)
            except Exception as exc:
                print(f"  ! click failed: {exc}", flush=True)

        await b.close()

    Path(OUT_DIR / "booking_xhr.json").write_text(
        json.dumps(captured, indent=2, ensure_ascii=False)
    )
    print(f"\n✅ Captured {len(captured)} XHRs", flush=True)
    print(f"   nav events: {nav_events}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
