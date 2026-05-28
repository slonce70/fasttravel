from __future__ import annotations

from shared.site_urls import public_destination_url, public_hotel_url


def test_public_hotel_url_normalizes_base_and_adds_telegram_medium() -> None:
    assert public_hotel_url(
        "https://web.fasttravel.test/root/",
        "fv-es-dolce-sitges",
        medium="deals",
    ) == (
        "https://web.fasttravel.test/root/hotels/fv-es-dolce-sitges"
        "?utm_source=tg_bot&utm_medium=deals"
    )


def test_public_hotel_url_requires_base_and_slug() -> None:
    assert public_hotel_url(None, "fv-es-dolce-sitges", medium="deals") is None
    assert public_hotel_url("https://web.fasttravel.test", None, medium="deals") is None


def test_public_hotel_url_strips_and_quotes_slug_path_segment() -> None:
    assert public_hotel_url("https://web.fasttravel.test/", " hotel slug/evil ") == (
        "https://web.fasttravel.test/hotels/hotel%20slug%2Fevil?utm_source=tg_bot"
    )


def test_public_destination_url_normalizes_country_code() -> None:
    assert public_destination_url("https://web.fasttravel.test/", " TR ") == (
        "https://web.fasttravel.test/destinations/tr?utm_source=tg_bot"
    )
