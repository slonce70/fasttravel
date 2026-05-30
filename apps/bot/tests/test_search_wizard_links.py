from __future__ import annotations

from src.handlers import wizard_render

_BASE = "https://fasttravel.com.ua"


def test_hit_renders_both_booking_and_site_buttons() -> None:
    # Now that apps/web /hotels/[slug] is live, every hit gets an operator
    # booking button AND an internal price-calendar button.
    rows = wizard_render.result_link_rows(
        [
            {
                "name_uk": "Bin Billa Hotel",
                "canonical_slug": "fv-tr-bin-billa-hotel",
                "deep_link": "https://farvater.travel/?q=abc",
            }
        ],
        site_base_url=_BASE,
    )

    assert len(rows) == 1
    row = rows[0]
    booking = next(b for b in row if "Забронювати" in b.text)
    assert booking.text == "🛒 Забронювати · Bin Billa Hotel"
    assert booking.url == "https://farvater.travel/?q=abc"
    site = next(b for b in row if b.url and "/hotels/" in b.url)
    assert site.url == (
        f"{_BASE}/hotels/fv-tr-bin-billa-hotel?utm_source=tg_bot&utm_medium=wizard"
    )


def test_site_only_hit_renders_when_deep_link_missing() -> None:
    # A hit without an operator deep link is no longer dropped — the internal
    # site button keeps it bookable via the price-calendar page.
    rows = wizard_render.result_link_rows(
        [{"name_uk": "No Link Hotel", "canonical_slug": "fv-tr-no-link"}],
        site_base_url=_BASE,
    )

    assert len(rows) == 1
    row = rows[0]
    assert all("Забронювати" not in b.text for b in row)  # no operator button
    site = next(b for b in row if b.url and "/hotels/" in b.url)
    assert site.url.startswith(f"{_BASE}/hotels/fv-tr-no-link")
    assert "No Link Hotel" in site.text  # name surfaces on the lone button


def test_operator_only_when_no_site_base() -> None:
    # Without a configured public site URL, fall back to operator-only (the
    # prior behaviour) — no broken /hotels/ button.
    rows = wizard_render.result_link_rows(
        [
            {
                "name_uk": "Bin Billa Hotel",
                "canonical_slug": "fv-tr-bin-billa-hotel",
                "deep_link": "https://farvater.travel/?q=ok",
            }
        ],
        site_base_url=None,
    )

    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].url == "https://farvater.travel/?q=ok"
    assert all("/hotels/" not in (b.url or "") for b in rows[0])


def test_hit_with_neither_deep_link_nor_resolvable_site_is_dropped() -> None:
    # No operator link and no slug → nothing to link to → drop the hit
    # (no broken/empty button rows).
    rows = wizard_render.result_link_rows(
        [{"name_uk": "Orphan"}],  # no deep_link, no canonical_slug
        site_base_url=_BASE,
    )
    assert rows == []

    # Same hit but also no site base → still dropped.
    rows_no_base = wizard_render.result_link_rows(
        [{"name_uk": "Orphan", "canonical_slug": "fv-tr-orphan"}],
        site_base_url=None,
    )
    assert rows_no_base == []


def test_results_markup_threads_site_base_url_into_link_rows() -> None:
    markup = wizard_render.results_markup(
        chunk=[
            {
                "name_uk": "Test Hotel",
                "canonical_slug": "fv-tr-test",
                "deep_link": "https://farvater.travel/?q=z",
            }
        ],
        has_prev=False,
        has_next=True,
        page=1,
        total_pages=2,
        subscribed=False,
        site_base_url=_BASE,
    )

    first_row = markup.inline_keyboard[0]
    # per-hit row carries both the operator and the internal site button…
    assert any(b.url == "https://farvater.travel/?q=z" for b in first_row)
    assert any(b.url and "/hotels/fv-tr-test" in b.url for b in first_row)
    # …followed by the nav/action rows from results_actions_kb.
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    assert "res:next" in callbacks
    assert "res:restart" in callbacks
    assert "res:subscribe" in callbacks
