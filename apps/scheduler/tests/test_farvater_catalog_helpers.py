from src.clients.farvater_catalog import (
    clean_description,
    clean_title,
    extract_gallery,
    extract_hotel_name,
    extract_stars,
    list_country_hotels,
    list_sitemap_hotels,
    make_slug,
    parse_jsonld,
    review_from_jsonld,
)


def test_catalog_helpers_clean_farvater_hotel_metadata() -> None:
    page = """
    <html>
      <head>
        <title>ᐉ Antik Butik (ex. Antik Hotel &amp; Garden) 4* - Туреччина - Farvater Travel</title>
        <meta property="og:image" content="https://img4.farvater.travel/hotelimages/hero?size=catalog">
        <script type="application/ld+json">
        {
          "description": "Real editor-written hotel description",
          "aggregateRating": {"ratingValue": "8.6", "reviewCount": "412"},
          "starRating": {"ratingValue": "4"}
        }
        </script>
      </head>
      <body>
        <img src="https://img4.farvater.travel/hotelimages/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?size=catalog">
        <img src="https://img4.farvater.travel/hotelimages/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?size=detail">
        <img src="https://img4.farvater.travel/hotelimages/ffffffff-1111-2222-3333-444444444444?size=detail">
      </body>
    </html>
    """

    jsonld = parse_jsonld(page)

    assert make_slug("TR", "/uk/hotel/tr/antik-butik/") == "fv-tr-antik-butik"
    assert (
        clean_title(
            "4* - тури в готель Дефне Стар Сіде - Farvater Travel",
            "/uk/hotel/tr/defne-star-hotel/",
        )
        == "Дефне Стар Сіде"
    )
    assert clean_description("Гіпермаркет турів ❶Ціни ❷Фото ☛ Farvater") is None
    assert extract_hotel_name(page, "/uk/hotel/tr/antik-butik/") == (
        "Antik Butik (ex. Antik Hotel & Garden)"
    )
    assert extract_gallery(page) == [
        "https://img4.farvater.travel/hotelimages/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?size=original",
        "https://img4.farvater.travel/hotelimages/ffffffff-1111-2222-3333-444444444444?size=original",
    ]
    assert review_from_jsonld(jsonld) == (8.6, 412)
    assert extract_stars(page) == 4


async def test_list_country_hotels_returns_unique_paths_in_page_order() -> None:
    class _Response:
        text = """
        <a href="/uk/hotel/tr/antik-butik/"></a>
        <a href="/uk/hotel/tr/antik-butik/"></a>
        <a href="/uk/hotel/eg/golf-villas-by-rixos/"></a>
        """

        def raise_for_status(self) -> None:
            return None

    class _Client:
        async def get(self, url: str, **kwargs: object) -> _Response:
            assert url == "https://farvater.travel/uk/hotelscatalog/strana-turkey/"
            assert kwargs["headers"] == {"User-Agent": "test-agent"}
            assert kwargs["timeout"] == 30
            return _Response()

    assert await list_country_hotels(_Client(), "turkey", user_agent="test-agent") == [
        "/uk/hotel/tr/antik-butik/",
        "/uk/hotel/eg/golf-villas-by-rixos/",
    ]


async def test_list_sitemap_hotels_groups_unique_supported_country_paths() -> None:
    class _Response:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class _Client:
        async def get(self, url: str, **kwargs: object) -> _Response:
            assert kwargs["headers"] == {"User-Agent": "test-agent"}
            if url == "https://farvater.travel/sitemap.xml":
                return _Response(
                    "<loc>https://farvater.travel/sitemap-hotelpages-1.xml</loc>"
                    "<loc>https://farvater.travel/sitemap-hotelpages-2.xml</loc>"
                )
            if url.endswith("sitemap-hotelpages-1.xml"):
                return _Response(
                    "<loc>https://farvater.travel/uk/hotel/tr/antik-butik/</loc>"
                    "<loc>https://farvater.travel/uk/hotel/tr/antik-butik/</loc>"
                    "<loc>https://farvater.travel/uk/hotel/es/costa-brava/</loc>"
                )
            if url.endswith("sitemap-hotelpages-2.xml"):
                return _Response(
                    "<loc>https://farvater.travel/uk/hotel/eg/golf-villas-by-rixos/</loc>"
                )
            raise AssertionError(f"unexpected url: {url}")

    assert await list_sitemap_hotels(
        _Client(), iso2_filter={"TR", "EG"}, user_agent="test-agent"
    ) == {
        "TR": ["/uk/hotel/tr/antik-butik/"],
        "EG": ["/uk/hotel/eg/golf-villas-by-rixos/"],
    }
