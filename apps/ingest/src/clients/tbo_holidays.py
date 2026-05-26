"""TBO Holidays Hotel API client.

Used for HOTEL CONTENT (photos, description, coords) — TBO does not
serve pricing for the UA market. The two endpoints we touch on MVP:
  * POST /HotelDetails — full content payload by hotel_code
  * POST /CityList — reference data (used by a separate seed script,
    not by the snapshot pipeline)

Auth is HTTP Basic; credentials live in env (TBO_USERNAME / TBO_PASSWORD).
If either is empty the constructor raises `TBONotConfigured` and
`pipeline.run_snapshot` records the run as `skipped_no_token`.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from src.clients.base import BaseClient
from src.exceptions import TBONotConfigured
from src.settings import get_settings


class TBOClient(BaseClient):
    source = "tbo"
    # TBO documents 20s as the hard ceiling; we use that.
    default_timeout_s = 20.0
    # Free TBO tier doesn't publish a concrete RPS — be polite.
    concurrency = 3

    def __init__(self) -> None:
        s = get_settings()
        if not s.tbo_username or not s.tbo_password:
            raise TBONotConfigured()
        self.base_url = s.tbo_api_base
        self._auth = httpx.BasicAuth(s.tbo_username, s.tbo_password)
        super().__init__()

    def _default_headers(self) -> dict[str, str]:
        return {
            **super()._default_headers(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def fetch_hotel_details(self, hotel_code: str) -> dict[str, Any]:
        """POST /HotelDetails with `{"Hotelcodes": "<code>", "Language": "EN"}`.

        Documented response shape (per apiintegration.tboholidays.com):
          {"Status": {"Code": 200, ...}, "HotelDetails": [{...}]}
        We return the parsed JSON as-is; the normalizer picks fields.
        """
        body = {"Hotelcodes": hotel_code, "Language": "EN"}
        response = await self._post("/HotelDetails", json=body, auth=self._auth)
        return cast(dict[str, Any], response.json())

    async def fetch_city_list(self, country_code: str) -> dict[str, Any]:
        """POST /CityList for reference seed data."""
        body = {"CountryCode": country_code}
        response = await self._post("/CityList", json=body, auth=self._auth)
        return cast(dict[str, Any], response.json())
