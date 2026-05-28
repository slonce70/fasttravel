"""SEO endpoints served by the API.

The frontend lives on Cloudflare Workers, but nginx routes `/robots.txt` and
`/sitemap.xml` to the API so these files can reflect the live hotel catalog.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from shared.site_urls import public_hotel_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from src.config import Settings
from src.deps import get_app_settings, get_db

router = APIRouter(tags=["seo"])

SITEMAP_LIMIT = 50_000


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt(settings: Settings = Depends(get_app_settings)) -> Response:
    public_site_url = settings.public_site_url.rstrip("/")
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {public_site_url}/sitemap.xml",
            "",
        ]
    )
    return Response(content=body, media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    public_site_url = settings.public_site_url.rstrip("/")
    rows = (
        await session.execute(
            text(
                """
                -- Only surface hotels users will see actual prices for.
                -- Indexing 40k+ empty calendars hurts crawl budget and trips
                -- Google's low-quality / soft-404 heuristics. Same gate /search
                -- and /destinations use, so /sitemap.xml stays consistent.
                SELECT canonical_slug
                FROM hotels
                WHERE is_active = true
                  AND has_active_prices = true
                  AND canonical_slug IS NOT NULL
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": SITEMAP_LIMIT},
        )
    ).all()

    urls: list[str] = []
    for row in rows:
        loc = public_hotel_url(public_site_url, row.canonical_slug, source="") or public_site_url
        urls.append(f"  <url><loc>{escape(loc)}</loc></url>")
    body = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            *urls,
            "</urlset>",
            "",
        ]
    )
    return Response(content=body, media_type="application/xml; charset=utf-8")
