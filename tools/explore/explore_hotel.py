"""Open a real farvater hotel page and capture every API call.

We now know the URL pattern: /uk/hotel/{country_code}/{hotel_slug}/.
The hotel detail page is where the price calendar / offers XHR fires.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, Response

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

HOTEL_URLS = [
    "https://farvater.travel/uk/hotel/eg/albatros-palace-resort-spa/",
    "https://farvater.travel/uk/hotel/eg/baron-palace/",
]


def _is_interesting(url: str, rtype: str) -> bool:
    if rtype not in ("xhr", "fetch", "document"):
        return False
    path = urlsplit(url).path
    junk = ("/partners/statistic", "/guest/log", "/guest/get-base", "/u/isLogin",
            "/u/crm/requestcode", "/agency-partner/isExist", "/health-srv/",
            "/cdn-cgi/", "/_next/static/", "/static/", "/sw.js", "/favicon")
    if any(j in path for j in junk):
        return False
    return True


async def run() -> None:
    captured: list[dict] = []
    seen = set()

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await b.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="uk-UA",
            timezone_id="Europe/Kyiv",
        )
        page = await ctx.new_page()

        async def on_resp(resp: Response) -> None:
            req = resp.request
            url, rtype = req.url, req.resource_type
            if not _is_interesting(url, rtype):
                return
            body = (req.post_data or "")[:5000]
            key = (req.method, url.split("?")[0], body[:200])
            if key in seen:
                return
            seen.add(key)

            text = None
            jsn = None
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" in ctype or "asmx" in url or "text" in ctype:
                try:
                    bb = await resp.body()
                    if bb and len(bb) < 4_000_000:
                        text = bb.decode("utf-8", errors="replace")
                        try:
                            jsn = json.loads(text)
                        except Exception:
                            pass
                except Exception:
                    pass

            captured.append({
                "method": req.method, "url": url, "status": resp.status,
                "request_body": body,
                "headers": {k.lower(): v for k, v in (req.headers or {}).items()
                            if k.lower() in ("content-type", "accept", "referer",
                                             "cookie", "x-csrf-token", "x-requested-with")},
                "response_content_type": ctype,
                "response_text_preview": (text or "")[:12000],
                "response_is_json": jsn is not None,
                "response_json_keys": list(jsn.keys())[:30] if isinstance(jsn, dict) else None,
                "response_size": len((text or "").encode("utf-8")),
            })
            print(f"  [{resp.status}] {req.method:5} {url[:180]}", flush=True)

        page.on("response", on_resp)

        for u in HOTEL_URLS:
            print(f"\n→ {u}", flush=True)
            try:
                await page.goto(u, wait_until="networkidle", timeout=90_000)
                # Hotel detail JS is heavy; wait long for calendar XHR
                await page.wait_for_timeout(15_000)

                # Try to expand the calendar/scroll to trigger lazy fetches.
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(3_000)
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(4_000)
            except Exception as exc:
                print(f"  ! error: {exc}", flush=True)

        await b.close()

    out = OUT_DIR / "hotel_capture.json"
    out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
    print(f"\n✅ {len(captured)} requests → {out}", flush=True)

    print("\n=== ENDPOINTS BY PATH ===", flush=True)
    by_path = {}
    for c in captured:
        p = urlsplit(c["url"]).path
        by_path.setdefault(p, []).append(c)
    for p, items in sorted(by_path.items(), key=lambda x: -len(x[1])):
        methods = sorted({i["method"] for i in items})
        statuses = sorted({i["status"] for i in items})
        json_n = sum(1 for i in items if i["response_is_json"])
        size_kb = sum(i["response_size"] for i in items) // 1024
        print(f"  {','.join(methods):8} {p[:90]:90} ×{len(items):2} status={statuses} json={json_n} kb={size_kb}")


if __name__ == "__main__":
    asyncio.run(run())
