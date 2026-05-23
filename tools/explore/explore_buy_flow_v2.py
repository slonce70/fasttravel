"""farvater buy-flow v2: click a calendar day FIRST, then chase the
real per-operator buy buttons that appear after."""
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
            "/agency-partner/", "/health-srv/", "/autocomplete/",
            "/hotel-reviews", "/hotelqa")
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

        new_pages = []
        ctx.on("page", lambda p: new_pages.append(p))

        # 1. Load hotel page, wait for calendar
        await page.goto(HOTEL_URL, wait_until="networkidle", timeout=90_000)
        await page.wait_for_timeout(10_000)

        # 2. Click "Обрати дату" - this turns the calendar into a picker
        try:
            await page.evaluate("""
            () => {
              const btn = Array.from(document.querySelectorAll('a, button'))
                .find(b => /обрати дату/i.test((b.innerText || '').trim()));
              if (btn) btn.click();
            }
            """)
            await page.wait_for_timeout(4_000)
        except Exception as exc:
            print(f"  ! 'Обрати дату' click error: {exc}", flush=True)

        # 3. Find any clickable calendar day with a price
        print("\n→ Inspecting calendar after 'Обрати дату'", flush=True)
        days = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll(
            '[class*="day"], [class*="cell"], td, button, a'
          ));
          return all.filter(el => {
            const t = (el.innerText || '').trim();
            // looks like a day cell with a price
            return /^\\d+\\s/.test(t) && /\\d+(?:\\s\\d{3})*\\s*(?:грн|UAH|\\$|€)/i.test(t);
          })
          .slice(0, 12)
          .map(el => ({
            text: el.innerText.replace(/\\s+/g, ' ').trim().slice(0, 80),
            tag: el.tagName,
            href: el.href || null,
            rect: (() => {
              const r = el.getBoundingClientRect();
              return { x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0 };
            })(),
          }));
        }
        """)
        print(f"  found {len(days)} day-cells with prices", flush=True)
        for d in days[:5]:
            print(f"    {d['tag']} pos=({d['rect']['x']},{d['rect']['y']}) text='{d['text'][:60]}'", flush=True)

        # 4. Click a day cell
        clicked_day = None
        if days:
            try:
                clicked_day = await page.evaluate("""
                () => {
                  const all = Array.from(document.querySelectorAll(
                    '[class*="day"], [class*="cell"], td, button, a'
                  ));
                  const day = all.find(el => {
                    const t = (el.innerText || '').trim();
                    return /^\\d+\\s/.test(t) && /\\d+(?:\\s\\d{3})*\\s*(?:грн|UAH|\\$|€)/i.test(t);
                  });
                  if (!day) return null;
                  day.scrollIntoView({ block: 'center' });
                  day.click();
                  return day.innerText.replace(/\\s+/g, ' ').trim().slice(0, 80);
                }
                """)
                await page.wait_for_timeout(8_000)
            except Exception as exc:
                print(f"  ! day click error: {exc}", flush=True)

        print(f"\n→ Clicked day = {clicked_day!r}", flush=True)
        print(f"  page.url AFTER day click = {page.url}", flush=True)

        # 5. After day click — find the operator buy buttons that appeared
        await page.screenshot(path=str(OUT / "buy_after_day.png"), full_page=True)

        offers = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('a, button, [role="button"]'));
          return all.filter(el => {
            const t = (el.innerText || '').trim();
            return /купити|замовити|обрати|перейти|book|buy|оформити/i.test(t)
                   && !/^обрати дату$/i.test(t)
                   && el.getBoundingClientRect().width > 30;
          }).slice(0, 15).map(el => ({
            tag: el.tagName,
            text: el.innerText.trim().slice(0, 80),
            href: el.href || null,
            onclick: el.getAttribute('onclick'),
            target: el.target || null,
            dataKeys: Array.from(el.attributes)
              .filter(a => a.name.startsWith('data-'))
              .map(a => `${a.name}=${a.value.slice(0, 80)}`).slice(0, 8),
            parentText: (el.closest('[class*="offer"], [class*="tour"], [class*="price"], [class*="item"], li')
              ?.innerText || '').replace(/\\s+/g, ' ').slice(0, 200),
            parentClass: (el.closest('[class*="offer"], [class*="tour"], [class*="price"], [class*="item"], li')
              ?.className || '').slice(0, 200),
          }));
        }
        """)
        Path(OUT / "operator_buy_candidates.json").write_text(
            json.dumps(offers, indent=2, ensure_ascii=False)
        )
        print(f"\n→ {len(offers)} buy candidates AFTER day click:", flush=True)
        for i, c in enumerate(offers[:6]):
            print(f"  [{i}] {c['tag']:6} '{c['text']}' href={c['href']!r}", flush=True)
            if c['parentText']:
                print(f"        ctx: {c['parentText'][:140]}", flush=True)
            if c['onclick']:
                print(f"        onclick: {c['onclick'][:120]}", flush=True)
            if c['dataKeys']:
                print(f"        data: {c['dataKeys']}", flush=True)

        # 6. Click the FIRST operator buy
        if offers:
            print(f"\n→ Clicking offer[0] '{offers[0]['text']}'", flush=True)
            try:
                await page.evaluate("""
                () => {
                  const all = Array.from(document.querySelectorAll('a, button, [role="button"]'));
                  const offers = all.filter(el => {
                    const t = (el.innerText || '').trim();
                    return /купити|замовити|обрати|перейти|book|buy|оформити/i.test(t)
                           && !/^обрати дату$/i.test(t)
                           && el.getBoundingClientRect().width > 30;
                  });
                  if (offers.length) offers[0].click();
                }
                """)
                await page.wait_for_timeout(8_000)
            except Exception as exc:
                print(f"  ! offer-click error: {exc}", flush=True)

            print(f"  page.url AFTER offer click = {page.url}", flush=True)
            for i, np in enumerate(new_pages):
                try:
                    print(f"  new tab[{i}] = {np.url}", flush=True)
                except Exception:
                    pass

        await page.screenshot(path=str(OUT / "buy_after_offer.png"), full_page=False)
        await b.close()

    Path(OUT / "buy_flow_v2_xhr.json").write_text(
        json.dumps(captured, indent=2, ensure_ascii=False)
    )
    print(f"\n✅ {len(captured)} XHRs", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
