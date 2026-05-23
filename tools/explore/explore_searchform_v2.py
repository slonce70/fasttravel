"""Focused: capture the pax popup HTML in full + full-page screenshots."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "out"


async def run() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])

        # ── Desktop full-page ───────────────────────────────────────────
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/121 Safari/537.36"),
            viewport={"width": 1440, "height": 900},
            locale="uk-UA", timezone_id="Europe/Kyiv",
        )
        page = await ctx.new_page()
        await page.goto("https://farvater.travel/uk/", wait_until="networkidle",
                         timeout=60_000)
        await page.wait_for_timeout(4500)

        # Crop the form region only — easier to read.
        await page.screenshot(path=str(OUT / "desktop_v2_form_only.png"),
                              clip={"x": 50, "y": 270, "width": 1340, "height": 200})

        # Click the 5th element in the form row — the "2 туриста" picker
        # (we know from default screenshot that pax is the 5th field).
        pax_html = await page.evaluate("""
        () => {
          // Find every element whose visible text contains "туриста" or "турист "
          const all = Array.from(document.querySelectorAll('*'));
          const cand = all.find(el => {
            const t = (el.innerText || '').trim();
            if (!t.match(/\\d+\\s+(туриста|турист|туристів)/i)) return false;
            const r = el.getBoundingClientRect();
            return r.width > 80 && r.width < 400 && r.height > 30 && r.height < 80
                    && r.top > 200 && r.top < 600;
          });
          if (!cand) return { found: false };
          cand.scrollIntoView({block: 'center'});
          cand.click();
          return { found: true, rect: (() => {const r=cand.getBoundingClientRect(); return {x:r.x|0,y:r.y|0,w:r.width|0,h:r.height|0};})(), text: cand.innerText.trim().slice(0,80) };
        }
        """)
        print(f"pax-picker click: {pax_html}", flush=True)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUT / "desktop_v2_pax_open.png"), full_page=False)

        # Capture the popup's full HTML structure
        popup_html = await page.evaluate("""
        () => {
          // Find any visible popover/modal/dropdown that appeared
          const popups = Array.from(document.querySelectorAll(
            '[class*="popup"], [class*="dropdown"], [class*="modal"], [class*="popover"], [role="dialog"]'
          )).filter(p => {
            const r = p.getBoundingClientRect();
            return r.width > 100 && r.height > 50 && getComputedStyle(p).display !== 'none';
          });
          return popups.map(p => ({
            classes: p.className.slice(0, 150),
            html: p.outerHTML.slice(0, 4500),
            rect: (() => {const r=p.getBoundingClientRect(); return {x:r.x|0,y:r.y|0,w:r.width|0,h:r.height|0};})(),
          }));
        }
        """)
        Path(OUT / "pax_popup_html.txt").write_text(
            "\n\n===== POPUP =====\n\n".join(
                f"classes={p['classes']}\nrect={p['rect']}\n\n{p['html']}"
                for p in popup_html
            )
        )
        print(f"pax popup HTML: {len(popup_html)} visible popups captured", flush=True)

        # ── Now look for additional toggles ROW BELOW main form
        extra_toggles = await page.evaluate("""
        () => {
          // The strip with checkboxes "Тури з останньої хвилини" etc.
          const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"], label, [class*="filter"], [class*="checkbox"]'));
          const visible = checkboxes.filter(el => {
            const r = el.getBoundingClientRect();
            return r.top > 350 && r.top < 600 && r.width > 50;
          });
          return visible.slice(0, 25).map(el => ({
            tag: el.tagName,
            type: el.type || '',
            text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
            classes: (el.className || '').slice(0, 100),
            rect: (() => {const r=el.getBoundingClientRect(); return {x:r.x|0,y:r.y|0};})(),
          }));
        }
        """)
        import json
        Path(OUT / "extra_toggles.json").write_text(json.dumps(extra_toggles, indent=2, ensure_ascii=False))
        print(f"extra toggles: {len(extra_toggles)}", flush=True)

        # ── Mobile full-page snapshot of the form
        mctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"),
            viewport={"width": 390, "height": 844},
            locale="uk-UA", timezone_id="Europe/Kyiv",
            is_mobile=True, has_touch=True,
        )
        mp = await mctx.new_page()
        await mp.goto("https://farvater.travel/uk/", wait_until="networkidle",
                       timeout=60_000)
        await mp.wait_for_timeout(4500)
        await mp.screenshot(path=str(OUT / "mobile_v2_full.png"), full_page=True)
        print(f"mobile full-page captured", flush=True)

        await browser.close()

    print("\nArtifacts:")
    for f in sorted(OUT.glob("desktop_v2_*")) + sorted(OUT.glob("mobile_v2_*")) + sorted(OUT.glob("pax_*")) + sorted(OUT.glob("extra_*")):
        print(f"  {f.name}  {f.stat().st_size}b")


if __name__ == "__main__":
    asyncio.run(run())
