"""Thin async HTTP client for the FastTravel API.

One module-level `httpx.AsyncClient` is held in `_CLIENT`. Aiogram
handlers reach it via `get_client()`; the bot entrypoint calls
`close_client()` on shutdown.

Why httpx and not aiohttp:
- The scheduler already pulls httpx (HTTP/2, retries). Sharing the same
  client surface in the bot keeps mental load down.
- httpx supports server-side timeouts cleanly via `httpx.Timeout`, which
  matters because the API has a few endpoints (search with a wide filter
  set) that can take 2-3s end-to-end.

Errors raise `ApiError` so handlers can render a single canned
"сервіс тимчасово недоступний" message without leaking 5xx bodies.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.config import get_settings
from src.infra.logging import get_logger

log = get_logger(__name__)


class ApiError(RuntimeError):
    """Raised when the upstream API is unreachable or returns a non-2xx."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


_CLIENT: httpx.AsyncClient | None = None


def _make_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(10.0, connect=3.0),
        # 2 retries on transient errors via transport-level retries — keeps
        # bot UX responsive without the handler needing to know.
        transport=httpx.AsyncHTTPTransport(retries=2),
        headers={"User-Agent": "FastTravel-Bot/1.0"},
    )


def get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = _make_client()
    return _CLIENT


async def close_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None


# ---------------------------------------------------------------------------
# Convenience methods — one per API endpoint we actually touch from the bot.
# Keep handler code free of httpx specifics.
# ---------------------------------------------------------------------------


async def get_destinations() -> list[dict[str, Any]]:
    """Returns the list of countries with `hotel_count` already filtered
    by `has_active_prices` (see apps/api/src/routers/destinations.py).
    Empty list on any error (handler decides how to surface that)."""
    try:
        r = await get_client().get("/api/destinations")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("api.destinations.failed", error=str(exc))
        raise ApiError("destinations fetch failed") from exc


async def search_hotels(**params: Any) -> dict[str, Any]:
    """`/api/search` — params match the route's query params verbatim.
    Returns the raw `PaginatedSearchResults` dict."""
    # Drop None values so we don't pollute the query string.
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    try:
        r = await get_client().get("/api/search", params=clean)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("api.search.failed", error=str(exc), params=clean)
        raise ApiError("search failed") from exc


async def get_deals(
    limit: int = 10,
    offset: int = 0,
    country: str | None = None,
    sort: str | None = None,
    nights_min: int | None = None,
    nights_max: int | None = None,
) -> dict[str, Any]:
    """`/api/deals` paginated.

    Args:
        limit/offset: standard pagination.
        country: optional ISO2 country filter.
        sort: ``discount`` (default upstream — biggest %), ``newest``,
            or ``price``. Passing ``None`` defers to the API's default.
        nights_min/nights_max: optional inclusive bounds on stay length.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if country:
        params["country"] = country
    if sort:
        params["sort"] = sort
    if nights_min is not None:
        params["nights_min"] = nights_min
    if nights_max is not None:
        params["nights_max"] = nights_max
    try:
        r = await get_client().get("/api/deals", params=params)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("api.deals.failed", error=str(exc))
        raise ApiError("deals fetch failed") from exc


async def get_hotel(slug: str) -> dict[str, Any] | None:
    """`/api/hotels/{slug}` — returns None on 404, raises on transport / 5xx."""
    try:
        r = await get_client().get(f"/api/hotels/{slug}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("api.hotel.failed", error=str(exc), slug=slug)
        raise ApiError("hotel fetch failed") from exc
