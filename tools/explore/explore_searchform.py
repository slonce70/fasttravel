"""Dump farvater's search form in full — pax/kids/ages, "Більше фільтрів" panel,
defaults, mobile layout. Output: out/searchform_structure.json (+ screenshots).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


async def dump_form_state(page) -> dict:
    """Snapshot all interactive elements in the search form area."""
    return await page.evaluate("""
    () => {
      // Search form sits near top of body; capture everything in the top 1200px.
      const form = document.querySelector('form') || document.body;
      const all = Array.from(form.querySelectorAll(
        'input, select, button, label, [role="combobox"], [role="button"], a'
      ));
      const visible = all.filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.top < 1200;
      });
      return visible.slice(0, 80).map(el => ({
        tag: el.tagName,
        type: (el.type || '').toLowerCase(),
        name: el.name || '',
        id: el.id || '',
        placeholder: el.placeholder || '',
        value: (typeof el.value === 'string' ? el.value : ''),
        text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
        aria: el.getAttribute('aria-label') || '',
        role: el.getAttribute('role') || '',
        classes: (el.className || '').slice(0, 200),
        dataAttrs: Array.from(el.attributes)
          .filter(a => a.name.startsWith('data-'))
          .map(a => `${a.name}=${a.value.slice(0, 80)}`),
        rect: (() => { const r = el.getBoundingClientRect(); return {
          x: r.x | 0, y: r.y | 0, w: r.width | 0, h: r.height | 0
        }; })(),
      }));
    }
    """)


async def run() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox"]
        )

        # ── DESKTOP ────────────────────────────────────────────────────
        desk_ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"),
            viewport={"width": 1440, "height": 1000},
            locale="uk-UA", timezone_id="Europe/Kyiv",
        )
        page = await desk_ctx.new_page()
        await page.goto("https://farvater.travel/uk/", wait_until="networkidle",
                         timeout=60_000)
        await page.wait_for_timeout(4500)
        await page.screenshot(path=str(OUT / "desktop_default.png"), full_page=False)

        desktop_state = await dump_form_state(page)
        (OUT / "desktop_form.json").write_text(
            json.dumps(desktop_state, indent=2, ensure_ascii=False)
        )
        print(f"desktop default: {len(desktop_state)} visible elements", flush=True)

        # Try to find and click pax/kids dropdown (туристи).
        for selector_q in [
            "text=/туристи/i", "text=/доросл/i", "text=/чоловік/i", "text=/гості/i",
            "[class*='passenger']", "[class*='tourist']", "[class*='pax']",
        ]:
            try:
                count = await page.locator(selector_q).count()
                if count:
                    print(f"  selector «{selector_q}»: {count} matches", flush=True)
            except Exception:
                pass

        # Click first element that looks like a passenger picker.
        clicked = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll(
            'input, button, [role="combobox"], [role="button"], div, span, label'
          ));
          const cand = all.find(el => {
            const t = (el.innerText || el.placeholder || el.value || '').toLowerCase();
            return /туристи?|доросл|дит|чоловік/i.test(t) && el.getBoundingClientRect().width > 50;
          });
          if (!cand) return null;
          cand.scrollIntoView({block: 'center'});
          cand.click();
          return cand.outerHTML.slice(0, 200);
        }
        """)
        print(f"  pax picker clicked: {clicked!s}", flush=True)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUT / "desktop_pax_open.png"), full_page=False)

        pax_state = await dump_form_state(page)
        (OUT / "desktop_pax_state.json").write_text(
            json.dumps(pax_state, indent=2, ensure_ascii=False)
        )

        # Try to open "More filters" / "Більше фільтрів"
        # Close pax popup first if open
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        more_clicked = await page.evaluate("""
        () => {
          const all = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'));
          const cand = all.find(el => {
            const t = (el.innerText || '').toLowerCase();
            return /більше фільтр|all filters|розшир|advanced/i.test(t);
          });
          if (!cand) return null;
          cand.scrollIntoView({block: 'center'});
          cand.click();
          return cand.outerHTML.slice(0, 200);
        }
        """)
        print(f"  more-filters clicked: {more_clicked!s}", flush=True)
        await page.wait_for_timeout(2500)
        await page.screenshot(path=str(OUT / "desktop_more_filters.png"), full_page=False)

        more_state = await dump_form_state(page)
        (OUT / "desktop_more_filters.json").write_text(
            json.dumps(more_state, indent=2, ensure_ascii=False)
        )

        # ── MOBILE ────────────────────────────────────────────────────
        mob_ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                        "Mobile/15E148 Safari/604.1"),
            viewport={"width": 390, "height": 844},  # iPhone 14
            locale="uk-UA", timezone_id="Europe/Kyiv",
            is_mobile=True, has_touch=True,
        )
        mp = await mob_ctx.new_page()
        await mp.goto("https://farvater.travel/uk/", wait_until="networkidle",
                       timeout=60_000)
        await mp.wait_for_timeout(4500)
        await mp.screenshot(path=str(OUT / "mobile_default.png"), full_page=False)
        mob_state = await dump_form_state(mp)
        (OUT / "mobile_form.json").write_text(
            json.dumps(mob_state, indent=2, ensure_ascii=False)
        )
        print(f"mobile default: {len(mob_state)} visible elements", flush=True)

        await browser.close()

    print("\n=== Artifacts written to out/ ===")
    for f in sorted(OUT.glob("*")):
        size = f.stat().st_size
        print(f"  {f.name}  ({size}b)")


if __name__ == "__main__":
    asyncio.run(run())
