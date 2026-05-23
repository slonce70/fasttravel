"""Reverse-engineer farvater.travel — capture XHR/fetch traffic of a tour search.

Goal: identify the JSON endpoints (search init, polling, price calendar,
hotel detail) so we can talk to them directly from
apps/ingest/clients/farvater_scraper.py and ditch synthetic seed data.

Strategy:
1. Launch headless Chromium with the page granted full network capture via CDP.
2. Navigate to farvater.travel/uk/ (homepage with search form).
3. If the homepage form is JS-rendered, also try a known deep URL that
   triggers a search immediately (e.g. /search/turkey).
4. Wait, then visit a specific hotel page so calendar XHR fires.
5. Write all observed XHR + fetch (URL, method, request body, response status,
   response body) to har.json + xhr_summary.json for analysis.

We deliberately do NOT load the full DOM/CSS for inspection — only network
traffic. Run time: ~30s.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, Request, Response

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

START_URLS = [
    "https://farvater.travel/uk/",
]

# After homepage load, also probe these to surface different XHR shapes.
DEEP_URLS = [
    # Search results page (common ittour-style slug; if 404 the page is just empty).
    "https://farvater.travel/uk/poshuk-turiv?strana=4&kurort=&dateFrom=2026-06-15&dateTo=2026-06-30&nights=7",
    # Random hotel page — we don't know any real slug, so we pick one we'll
    # discover during homepage browsing. Fallback to /hotels/ index if needed.
]


# Filters: only XHR/fetch + only origin requests, drop noise (analytics, fonts).
def _is_interesting(url: str, resource_type: str) -> bool:
    if resource_type not in ("xhr", "fetch", "document"):
        return False
    host = urlsplit(url).netloc.lower()
    if not host.endswith("farvater.travel") and not host.endswith("farvater.ua"):
        # Allow ittour subdomains too — sometimes aggregator widgets call ittour direct.
        if "ittour" not in host and "tat.ua" not in host and "otpusk" not in host:
            return False
    junk_paths = ("/analytics", "/gtag", "/gtm", "/static/", "/_next/static/",
                  "/sw.js", "/favicon", "/__/firebase", "/sockjs-node")
    path = urlsplit(url).path
    if any(j in path for j in junk_paths):
        return False
    # Allow .asmx (ASP.NET web service — ittour signature)
    return True


async def run() -> None:
    captured: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()  # dedup (method, url, body_hash)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="uk-UA",
            timezone_id="Europe/Kyiv",
        )
        page = await context.new_page()

        async def on_response(resp: Response) -> None:
            req = resp.request
            url = req.url
            rtype = req.resource_type
            if not _is_interesting(url, rtype):
                return
            body_repr = ""
            try:
                rd = req.post_data
                if rd:
                    body_repr = rd[:2000]
            except Exception:
                pass
            key = (req.method, url.split("?")[0], body_repr[:200])
            if key in seen_keys:
                return
            seen_keys.add(key)

            # Try to read response body for JSON-ish; skip if large/binary.
            response_text: str | None = None
            response_json = None
            ctype = (resp.headers or {}).get("content-type", "")
            if "application/json" in ctype or "text/" in ctype or "asmx" in url:
                try:
                    body_bytes = await resp.body()
                    if body_bytes and len(body_bytes) < 800_000:
                        response_text = body_bytes.decode("utf-8", errors="replace")
                        try:
                            response_json = json.loads(response_text)
                        except Exception:
                            response_json = None
                except Exception:
                    pass

            captured.append({
                "method": req.method,
                "url": url,
                "resource_type": rtype,
                "status": resp.status,
                "request_headers": {k.lower(): v for k, v in (req.headers or {}).items()
                                     if k.lower() in ("content-type", "accept", "x-requested-with",
                                                       "authorization", "cookie")},
                "request_body": body_repr,
                "response_content_type": ctype,
                "response_text_preview": (response_text or "")[:4000],
                "response_is_json": response_json is not None,
                "response_json_keys": (
                    list(response_json.keys())[:30] if isinstance(response_json, dict) else None
                ),
            })
            print(f"  [{resp.status}] {req.method} {url[:160]}", flush=True)

        page.on("response", on_response)

        for url in START_URLS:
            print(f"\n→ Visiting {url}", flush=True)
            try:
                await page.goto(url, wait_until="networkidle", timeout=60_000)
            except Exception as exc:
                print(f"  ! goto failed: {exc}", flush=True)
                continue

            # Let JS-driven XHR settle.
            await page.wait_for_timeout(4000)

            # Try to find a hotel/search link inside the page DOM.
            try:
                hotel_links = await page.evaluate(
                    "Array.from(document.querySelectorAll('a[href*=\"hotel\"]'))"
                    ".map(a => a.href).slice(0, 8)"
                )
                print(f"  hotel links found: {hotel_links}", flush=True)
            except Exception:
                hotel_links = []

            # Click first hotel link if any.
            if hotel_links:
                target = hotel_links[0]
                print(f"\n→ Visiting first hotel: {target}", flush=True)
                try:
                    await page.goto(target, wait_until="networkidle", timeout=60_000)
                    await page.wait_for_timeout(4000)
                except Exception as exc:
                    print(f"  ! hotel goto failed: {exc}", flush=True)

        for url in DEEP_URLS:
            print(f"\n→ Probing {url}", flush=True)
            try:
                await page.goto(url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(3000)
            except Exception as exc:
                print(f"  ! probe failed: {exc}", flush=True)

        await browser.close()

    out_path = OUT_DIR / "xhr_capture.json"
    out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
    print(f"\n✅ Captured {len(captured)} interesting requests → {out_path}", flush=True)

    # Summary by URL pattern.
    print("\n=== Endpoint summary ===")
    by_path: dict[str, list[dict]] = {}
    for c in captured:
        p = urlsplit(c["url"]).path
        by_path.setdefault(p, []).append(c)
    for p, items in sorted(by_path.items(), key=lambda x: -len(x[1])):
        methods = sorted({i["method"] for i in items})
        statuses = sorted({i["status"] for i in items})
        json_n = sum(1 for i in items if i["response_is_json"])
        print(f"  {','.join(methods):8} {p[:90]:90} count={len(items):2} status={statuses} json={json_n}")


if __name__ == "__main__":
    asyncio.run(run())
