from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_robots_txt_points_to_public_sitemap(client: AsyncClient) -> None:
    response = await client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in response.text
    assert "Allow: /" in response.text
    assert "Sitemap: https://fasttravel.com.ua/sitemap.xml" in response.text


@pytest.mark.asyncio
async def test_sitemap_xml_lists_active_hotel_slugs_only(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
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
                canonical_slug, name_uk, name_en, destination_id, is_active
            )
            VALUES
                ('seo-test-active-hotel', 'SEO Active Hotel', 'SEO Active Hotel', :dest, true),
                ('seo-test-inactive-hotel', 'SEO Inactive Hotel', 'SEO Inactive Hotel', :dest, false)
            """
        ),
        {"dest": dest_id},
    )

    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in response.text
    assert "<loc>https://fasttravel.com.ua/hotels/seo-test-active-hotel</loc>" in response.text
    assert "seo-test-inactive-hotel" not in response.text
