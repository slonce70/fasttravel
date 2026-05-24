from src.jobs.snapshot_farvater import _clean_title


def test_clean_title_uses_slug_fallback_for_farvater_boilerplate() -> None:
    assert (
        _clean_title("ᐉ - Farvater Travel", "/uk/hotel/eg/golf-villas-by-rixos/")
        == "Golf Villas By Rixos"
    )


def test_clean_title_extracts_hotel_name_from_tours_title() -> None:
    assert (
        _clean_title(
            "4* - тури в готель Дефне Стар Сіде - Farvater Travel",
            "/uk/hotel/tr/defne-star-hotel/",
        )
        == "Дефне Стар Сіде"
    )


def test_clean_title_unescapes_entities_and_drops_example_tail() -> None:
    assert (
        _clean_title(
            "Bellagio Beach Resort &amp; Spa (наприклад ціни) - Farvater Travel",
            "/uk/hotel/eg/panorama-bungalows-resort-hurghada/",
        )
        == "Bellagio Beach Resort & Spa"
    )


def test_clean_title_uses_slug_fallback_for_ex_only_title() -> None:
    assert (
        _clean_title(
            "ᐉ (ex. Belport Beach Hotel) 4* - Farvater Travel",
            "/uk/hotel/tr/belport-beach-hotel/",
        )
        == "Belport Beach Hotel"
    )
