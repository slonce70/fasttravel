from __future__ import annotations

from src.handlers import deals


def test_deals_keyboard_uses_single_hotel_button_for_deep_link(monkeypatch) -> None:
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: type("Settings", (), {"public_site_url": "https://web.fasttravel.test"})(),
    )

    keyboard = deals._build_keyboard(
        [
            {
                "hotel_name_uk": "Dolce Sitges",
                "hotel_slug": "fv-es-dolce-sitges",
                "deep_link": "https://farvater.travel/uk/hotel/es/dolce-sitges?q=abc",
            }
        ],
        page=1,
        total_pages=1,
    )

    first_row = keyboard.inline_keyboard[0]
    assert len(first_row) == 1
    assert first_row[0].text == "📖 Dolce Sitges"
    assert first_row[0].url == "https://farvater.travel/uk/hotel/es/dolce-sitges?q=abc"
    assert all(button.text != "🛒 Купити" for row in keyboard.inline_keyboard for button in row)


def test_deals_keyboard_falls_back_to_site_url_when_no_deep_link(monkeypatch) -> None:
    monkeypatch.setattr(
        deals,
        "get_settings",
        lambda: type("Settings", (), {"public_site_url": "https://web.fasttravel.test"})(),
    )

    keyboard = deals._build_keyboard(
        [
            {
                "hotel_name_uk": "Dolce Sitges",
                "hotel_slug": "fv-es-dolce-sitges",
                "deep_link": None,
            }
        ],
        page=1,
        total_pages=1,
    )

    assert keyboard.inline_keyboard[0][0].url == (
        "https://web.fasttravel.test/hotels/fv-es-dolce-sitges?utm_source=tg_bot&utm_medium=deals"
    )
