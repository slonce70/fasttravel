from __future__ import annotations

from src.handlers import wizard_render


def test_result_rows_render_single_booking_button_per_hit() -> None:
    rows = wizard_render.result_link_rows(
        [
            {
                "name_uk": "Bin Billa Hotel",
                "canonical_slug": "fv-tr-bin-billa-hotel",
                "deep_link": "https://farvater.travel/?q=abc",
            }
        ]
    )

    assert len(rows) == 1
    # One button per hit — the internal-site (📖) button was removed because
    # the web app at public_site_url 404s on /hotels/{slug}. Keeping a
    # broken link only confused users.
    assert len(rows[0]) == 1
    assert rows[0][0].text == "🛒 Забронювати · Bin Billa Hotel"
    assert rows[0][0].url == "https://farvater.travel/?q=abc"


def test_result_rows_skip_hits_without_deep_link() -> None:
    rows = wizard_render.result_link_rows(
        [
            {"name_uk": "No Link Hotel", "canonical_slug": "fv-tr-no-link"},
            {
                "name_uk": "With Link",
                "canonical_slug": "fv-tr-with-link",
                "deep_link": "https://farvater.travel/?q=ok",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0][0].url == "https://farvater.travel/?q=ok"


def test_results_markup_prepends_booking_buttons_to_nav_actions() -> None:
    markup = wizard_render.results_markup(
        chunk=[{"name_uk": "Test Hotel", "deep_link": "https://farvater.travel/?q=z"}],
        has_prev=False,
        has_next=True,
        page=1,
        total_pages=2,
        subscribed=False,
    )

    # First row is the per-hit booking button…
    assert markup.inline_keyboard[0][0].text == "🛒 Забронювати · Test Hotel"
    assert markup.inline_keyboard[0][0].url == "https://farvater.travel/?q=z"
    # …followed by the nav/action rows from results_actions_kb.
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    assert "res:next" in callbacks
    assert "res:restart" in callbacks
    assert "res:subscribe" in callbacks
