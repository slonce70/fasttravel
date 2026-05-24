"""Module-level slowapi limiter shared by all routers.

Lives in `src.infra` (not `src.main`) so router modules can import the
limiter without circular-importing the FastAPI app. `src.main` reads
this same instance into `app.state.limiter` so slowapi's middleware +
exception handler pick it up.

`get_remote_address` keys on `X-Forwarded-For` first (set by nginx in
prod) and falls back to the socket peer. In local-dev compose without
nginx that means every request looks like it comes from
172.20.0.1 — for dev that's fine; in prod each visitor is correctly
distinguished by their client IP.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
