"""Module-level slowapi limiter shared by all routers.

Lives in `src.infra` (not `src.main`) so router modules can import the
limiter without circular-importing the FastAPI app. `src.main` reads
this same instance into `app.state.limiter` so slowapi's middleware +
exception handler pick it up.

Keying strategy (audit fix — was using slowapi's `get_remote_address`
which only reads `request.client.host`; behind nginx in prod every
request comes from the nginx-egress IP so a `10/hour` rule was
*global* instead of per-visitor):

  1. ``CF-Connecting-IP``  — Cloudflare passes the original visitor IP
     here when the API is behind their proxy.
  2. ``X-Forwarded-For``[0] — first hop of the XFF chain, set by nginx
     when CF is bypassed.
  3. ``request.client.host`` — direct connection fallback (local dev,
     internal-network healthchecks).

Operators who put a different proxy in front (Caddy, Traefik, raw
Cloudflare Worker) can override the header preference with the
``RATE_LIMIT_TRUSTED_HEADER`` env var — comma-separated list checked in
order. Defaults to ``CF-Connecting-IP,X-Forwarded-For``.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from starlette.requests import Request

_DEFAULT_HEADERS = ("CF-Connecting-IP", "X-Forwarded-For")


def _client_ip(request: Request) -> str:
    """Resolve the canonical visitor IP. Always returns a non-empty
    string so slowapi never sees ``None`` (which would silently bucket
    every unkeyable request together)."""
    raw = os.getenv("RATE_LIMIT_TRUSTED_HEADER", "")
    headers = tuple(h.strip() for h in raw.split(",") if h.strip()) or _DEFAULT_HEADERS

    for name in headers:
        value = request.headers.get(name)
        if not value:
            continue
        # XFF can be "client, proxy1, proxy2" — first hop is the
        # original client.
        first = value.split(",", 1)[0].strip()
        if first:
            return first

    # Direct connection (no proxy) — fall back to the socket peer.
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


limiter = Limiter(key_func=_client_ip)
