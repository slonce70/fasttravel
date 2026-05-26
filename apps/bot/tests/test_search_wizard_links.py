from __future__ import annotations

from src.handlers import search_wizard


def test_result_rows_use_farvater_deep_link_without_public_site(monkeypatch) -> None:
    monkeypatch.setattr(
        search_wizard,
        "get_settings",
        lambda: type("Settings", (), {"public_site_url": None})(),
    )

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
    assert len(rows[0]) == 1
    assert rows[0][0].text == "🛒 Bin Billa Hotel"
    assert rows[0][0].url == "https://farvater.travel/?q=abc"


def test_result_rows_add_site_link_only_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        search_wizard,
        "get_settings",
        lambda: type(
            "Settings", (), {"public_site_url": "https://web.fasttravel.test"}
        )(),
    )

    rows = search_wizard._result_link_rows(
        [
            {
                "name_uk": "Bin Billa Hotel",
                "canonical_slug": "fv-tr-bin-billa-hotel",
                "deep_link": "https://farvater.travel/?q=abc",
            }
        ]
    )

    assert len(rows[0]) == 2
    assert rows[0][0].url == (
        "https://web.fasttravel.test/hotels/fv-tr-bin-billa-hotel"
        "?utm_source=tg_bot&utm_medium=wizard"
    )
    assert rows[0][1].url == "https://farvater.travel/?q=abc"
