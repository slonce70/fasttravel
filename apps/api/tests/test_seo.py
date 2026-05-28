from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_app_settings
from src.main import app


@pytest.mark.asyncio
async def test_robots_txt_points_to_public_sitemap(client: AsyncClient) -> None:
    response = await client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in response.text
    assert "Allow: /" in response.text
    assert "Sitemap: https://fasttravel.com.ua/sitemap.xml" in response.text


@pytest.mark.asyncio
async def test_robots_txt_uses_configured_public_site_url() -> None:
    app.dependency_overrides[get_app_settings] = lambda: SimpleNamespace(
        public_site_url="https://seo.fasttravel.test/root/"
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/robots.txt")

    assert "Sitemap: https://seo.fasttravel.test/root/sitemap.xml" in response.text
    assert "https://fasttravel.com.ua" not in response.text
    app.dependency_overrides.pop(get_app_settings, None)


@pytest.mark.asyncio
async def test_sitemap_xml_lists_priced_hotel_slugs_only(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sitemap must only list hotels with active prices.

    A hotel that's `is_active=true` but `has_active_prices=false` is
    catalogued-but-empty — exposing it would direct crawlers at pages
    that render an empty calendar. The same gate /search and
    /destinations use, so all three views stay consistent.
    """
    dest_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('ZZ', 'seo-test-country', 'SEO Test Country', 'SEO Test Country')
                RETURNING id
                """
            )
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, name_en, destination_id,
                is_active, has_active_prices
            )
            VALUES
                ('seo-test-priced-hotel',   'SEO Priced Hotel',   'SEO Priced Hotel',   :dest, true,  true),
                ('seo-test-unpriced-hotel', 'SEO Unpriced Hotel', 'SEO Unpriced Hotel', :dest, true,  false),
                ('seo-test-inactive-hotel', 'SEO Inactive Hotel', 'SEO Inactive Hotel', :dest, false, true)
            """
        ),
        {"dest": dest_id},
    )

    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in response.text
    assert "<loc>https://fasttravel.com.ua/hotels/seo-test-priced-hotel</loc>" in response.text
    assert "seo-test-unpriced-hotel" not in response.text
    assert "seo-test-inactive-hotel" not in response.text


@pytest.mark.asyncio
async def test_sitemap_xml_uses_configured_public_site_url(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    app.dependency_overrides[get_app_settings] = lambda: SimpleNamespace(
        public_site_url="https://seo.fasttravel.test/root/"
    )
    dest_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('ZX', 'seo-config-country', 'SEO Config Country', 'SEO Config Country')
                RETURNING id
                """
            )
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO hotels (
                canonical_slug, name_uk, name_en, destination_id,
                is_active, has_active_prices
            )
            VALUES ('seo-config-priced-hotel', 'SEO Config Hotel', 'SEO Config Hotel', :dest, true, true)
            """
        ),
        {"dest": dest_id},
    )

    response = await client.get("/sitemap.xml")

    assert (
        "<loc>https://seo.fasttravel.test/root/hotels/seo-config-priced-hotel</loc>"
        in response.text
    )
    assert "https://fasttravel.com.ua/hotels/seo-config-priced-hotel" not in response.text
