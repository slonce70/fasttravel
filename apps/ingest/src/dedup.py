"""Offer-level deduplication via Redis.

Rationale: we run a snapshot twice per day across thousands of
hotel x config combinations. Most of those combinations will return
EXACTLY the same price between morning and evening — operators
re-quote relatively rarely. If we let every observation hit
`price_observations`, the table doubles in size for nothing.

Strategy: hash the offer's load-bearing fields. The first
observer of a fingerprint within the TTL window wins; subsequent
identical fingerprints are skipped silently.

Trade-off: we lose the "observed at 06:00 AND 18:00 with same price"
evidence. That's fine — the deal detector cares about CHANGES,
not stability. If a price never changes, the absence of new rows
IS the signal that it stayed put.
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis

from src.normalizers.base import NormalizedOffer
from src.settings import get_settings

_PREFIX = "ingest:dedup:"


def offer_fingerprint(offer: NormalizedOffer) -> str:
    """Stable hash of the offer's identity + price.

    Note that `deep_link` is included: operators sometimes serve
    the SAME price but with a different `utm_*` or `priceTimestamp`
    in the URL. Treating those as duplicate is fine — the price is
    what matters for deal detection.
    """
    payload = (
        f"{offer.hotel_external_id}|{offer.operator_code}|{offer.check_in.isoformat()}"
        f"|{offer.nights}|{offer.meal_plan}|{offer.price_uah}"
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


async def is_duplicate(redis: Redis, fingerprint: str, ttl_hours: int | None = None) -> bool:
    """Return True if we've seen this exact fingerprint in the TTL window.

    Side effect on False: the fingerprint is registered with TTL so the
    NEXT identical observation returns True. This is the only correct
    way to do this atomically (SET NX EX) — separate GET+SET would race.
    """
    ttl = ttl_hours if ttl_hours is not None else get_settings().dedup_ttl_hours
    key = f"{_PREFIX}{fingerprint}"
    # SET NX EX returns True (key set) if NEW, None if it already existed.
    was_set = await redis.set(key, "1", nx=True, ex=ttl * 3600)
    return not bool(was_set)
