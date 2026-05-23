from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HotelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_slug: str
    name_uk: str
    name_en: str | None = None
    stars: int | None = None
    destination_id: int | None = None
    review_score: float | None = None
    review_count: int = 0
    photos_jsonb: list[dict[str, Any]] | None = Field(default=None, alias="photos_jsonb")
    amenities: list[str] | None = None
    description_uk: str | None = None
    last_updated: datetime | None = None
    is_active: bool = True
