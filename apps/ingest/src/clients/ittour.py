"""ittour.com.ua API client.

Authentication: bearer token + IP allowlist. The Reserved Public IP of
the Oracle VM gets whitelisted with ittour; we echo that IP back as
`X-Source-Ip` so their gateway logs match.

Search is two-phase:
  1) POST /search/init  → {uuid: "..."}                  (kicks off the query)
  2) GET  /search/results?uuid=...  → {status, offers}   (poll until done)

The exact endpoint paths and response shapes here are based on the
public documentation snapshot we have. Both will need verification
against the canonical docs once the account contract is signed.
TODO(@user): confirm the following once ittour ships final docs:
  * path of init endpoint (could be /v1/search/init or /search/start)
  * polling status enum (we assume "pending" / "done" / "failed")
  * offer payload field names — see ittour_normalizer.py for assumptions

If ITTOUR_API_TOKEN is empty, the client refuses to instantiate; the
pipeline catches `ITTourNotConfigured` and records a skipped run.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from src.clients.base import BaseClient
from src.exceptions import ITTourNotConfigured, IngestError
from src.settings import get_settings


class ITTourClient(BaseClient):
    source = "ittour"
    default_timeout_s = 30.0
    concurrency = 5
    # ittour publicly advertises ~10 RPS for partner tiers; we stay
    # comfortably below until we observe real throughput.
    min_request_interval_s = 0.2

    def __init__(self) -> None:
        s = get_settings()
        if not s.ittour_api_token:
            raise ITTourNotConfigured()
        self.base_url = s.ittour_api_base
        self._token = s.ittour_api_token
        self._source_ip = s.ittour_source_ip
        self._poll_timeout_s = s.ittour_search_poll_timeout_s
        self._poll_interval_s = s.ittour_search_poll_interval_s
        super().__init__()

    def _default_headers(self) -> dict[str, str]:
        h = {
            **super()._default_headers(),
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._source_ip:
            h["X-Source-Ip"] = self._source_ip
        return h

    # ----- search ----------------------------------------------------------

    async def search_offers(
        self,
        *,
        country: str,
        region: str | None,
        check_in_min: date,
        check_in_max: date,
        nights: int,
        adults: int = 2,
        children: int = 0,
        meal_plan: str | None = None,
        departure_city: str | None = None,
    ) -> list[dict[str, Any]]:
        """Two-phase search: init → poll → return raw offers list."""
        body = {
            "country": country,
            "region": region,
            "check_in_min": check_in_min.isoformat(),
            "check_in_max": check_in_max.isoformat(),
            "nights": nights,
            "adults": adults,
            "children": children,
            "meal_plan": meal_plan,
            "departure_city": departure_city,
        }
        # TODO(@user): verify "/search/init" path against canonical docs
        init_resp = await self._post("/search/init", json=body)
        init_payload = init_resp.json()
        search_uuid = init_payload.get("uuid")
        if not search_uuid:
            raise IngestError(f"ittour init response missing uuid: {init_payload!r}")

        return await self._poll_search_results(search_uuid)

    async def _poll_search_results(self, search_uuid: str) -> list[dict[str, Any]]:
        deadline = self._poll_timeout_s
        elapsed = 0.0
        while elapsed < deadline:
            # TODO(@user): verify path "/search/results"
            resp = await self._get("/search/results", params={"uuid": search_uuid})
            data = resp.json()
            status = data.get("status")
            if status == "done":
                offers = data.get("offers") or []
                return list(offers)
            if status == "failed":
                raise IngestError(
                    f"ittour search {search_uuid} failed: {data.get('error')!r}"
                )
            await asyncio.sleep(self._poll_interval_s)
            elapsed += self._poll_interval_s
        raise IngestError(f"ittour search {search_uuid} timed out after {deadline}s")

    # ----- hotel content ---------------------------------------------------

    async def fetch_hotel(self, hotel_id: str) -> dict[str, Any]:
        # TODO(@user): verify path "/hotels/{id}"
        resp = await self._get(f"/hotels/{hotel_id}")
        return resp.json()

    async def fetch_hotel_calendar(
        self, hotel_id: str, from_date: date, to_date: date
    ) -> dict[str, Any]:
        # TODO(@user): verify path "/hotels/{id}/calendar"
        resp = await self._get(
            f"/hotels/{hotel_id}/calendar",
            params={"from": from_date.isoformat(), "to": to_date.isoformat()},
        )
        return resp.json()
