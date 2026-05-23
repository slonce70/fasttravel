"""Shared dataclasses + helper lookup tables for the three source normalizers.

NormalizedOffer ↔ `price_observations` table:
  hotel_external_id  → resolved via hotel_operator_mapping to hotel_id
  operator_code      → resolved to operator_id at insert time
  the rest map column-for-column.

NormalizedHotelContent → `hotels` table (UPSERT path, not implemented
here — that lives in pipeline.py / a separate content-refresh job).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Canonical meal-plan vocabulary. `price_observations.meal_plan` is VARCHAR(16),
# so we lock the value set so the deal-detection SQL doesn't have to handle
# "All Inclusive", "ALL INCL.", "all incl", etc.
# ---------------------------------------------------------------------------
MEAL_PLAN_CANONICAL = {"AI", "UAI", "HB", "BB", "FB", "RO", "OTHER"}

#: Lowercase substring → canonical code. Order is insignificant; first
#: match wins. The "OTHER" bucket is the explicit unknown — never silent.
MEAL_PLAN_ALIASES: dict[str, str] = {
    "ultra all": "UAI",
    "uai": "UAI",
    "all inclusive": "AI",
    "all incl": "AI",
    "ai": "AI",
    "half board": "HB",
    "hb": "HB",
    "bed and breakfast": "BB",
    "breakfast": "BB",
    "bb": "BB",
    "full board": "FB",
    "fb": "FB",
    "room only": "RO",
    "no meal": "RO",
    "ro": "RO",
}


def normalize_meal_plan(raw: str | None) -> str:
    """Map a free-form meal plan string to the canonical code set.

    Unknown → "OTHER". The caller logs a warn before/after so we can keep
    track of new vocabulary creeping in from upstream.
    """
    if not raw:
        return "OTHER"
    key = raw.strip().lower()
    for alias, code in MEAL_PLAN_ALIASES.items():
        if alias in key:
            return code
    return "OTHER"


@dataclass(slots=True)
class NormalizedOffer:
    """One row destined for `price_observations`.

    `raw_payload` is kept so we can replay normalization against an
    archived row when we change the normalizer logic.
    """

    hotel_external_id: str
    operator_code: str
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    price_original: int
    currency: str
    fx_rate_to_uah: Decimal
    deep_link: str
    room_category: str | None = None
    adults: int = 2
    departure_city: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedHotelContent:
    """Hotel-level metadata destined for `hotels`."""

    external_id: str
    name: str
    stars: int | None = None
    coords: tuple[float, float] | None = None
    photos: list[str] = field(default_factory=list)
    description: str | None = None
    amenities: list[str] = field(default_factory=list)
    review_score: float | None = None
    review_count: int | None = None
