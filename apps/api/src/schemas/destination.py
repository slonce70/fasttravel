"""Pydantic schemas for the /api/destinations endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegionOut(BaseModel):
    """A region (resort) nested under a country."""

    id: int
    region_slug: str
    name_uk: str
    name_en: str | None = None
    hotel_count: int = 0


class CountryOut(BaseModel):
    """A country with its regions and hotel counts.

    Used by the frontend country selector and to generate static
    `/destinations/[country]/page.tsx` pages.
    """

    id: int
    country_iso2: str = Field(min_length=2, max_length=2)
    country_slug: str = Field(
        description="URL-safe slug, lowercased name_en ('turkey', 'egypt')",
    )
    name_uk: str
    name_en: str | None = None
    hotel_count: int = 0
    regions: list[RegionOut] = []
