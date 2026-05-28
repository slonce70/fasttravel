from __future__ import annotations

import httpx
import pytest

from src.clients.farvater_hotel_page import fetch_hotel_meta


async def test_fetch_hotel_meta_treats_404_as_expected_stale_url() -> None:
    class _NotFoundClient:
        async def get_text(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            request = httpx.Request("GET", "https://farvater.travel/uk/hotel/tr/stale/")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    result = await fetch_hotel_meta(_NotFoundClient(), "/uk/hotel/tr/stale/", "TR")

    assert result is None


async def test_fetch_hotel_meta_raises_on_transient_http_error() -> None:
    class _ServerErrorClient:
        async def get_text(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            request = httpx.Request("GET", "https://farvater.travel/uk/hotel/tr/live/")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)

    with pytest.raises(Exception, match="transient"):
        await fetch_hotel_meta(_ServerErrorClient(), "/uk/hotel/tr/live/", "TR")
