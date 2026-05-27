from __future__ import annotations

from src.handlers import search_wizard


def test_result_rows_render_single_booking_button_per_hit() -> None:
    rows = search_wizard._result_link_rows(
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
    rows = search_wizard._result_link_rows(
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
