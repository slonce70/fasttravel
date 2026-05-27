"""Custom ASGI middlewares.

Audit #1.3 High — the search router doubled every query-param signature
to accept `amp;<name>` aliases (workaround for SEO crawlers that send
HTML-escaped `&amp;` in URLs). That polluted OpenAPI, doubled the
signature surface, and the same problem would surface on every future
router. Better fix: rewrite the raw query string before the router sees
it. One middleware, the routers stay clean.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send


class AmpQueryParamMiddleware:
    """Rewrites `?amp;param=value` → `?param=value` before route matching.

    Why it matters: SEO crawlers (Twitterbot, some link previewers) take
    the `&` from a hand-crafted query string and HTML-escape it to
    `&amp;`. Browsers handle that, but Starlette's URL parser passes
    the literal `amp;param=…` to the route — so `?country=tr` works,
    `?amp;country=tr` returns 422 unless the route declared an alias.

    We mutate the raw `scope["query_string"]` bytes BEFORE Starlette's
    URL/Query parsing runs. Operates on the ASGI scope so it covers
    BOTH the path-matching pass (FastAPI's route table) AND the
    Query(...) extraction pass.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            qs: bytes = scope.get("query_string", b"")
            if b"amp;" in qs:
                # Replace `amp;` only when it directly follows `?` or `&`
                # so we don't smash a legitimate value that happens to
                # contain the substring (e.g. `?utm_source=lamp;day=mon`
                # — yes, contrived, but the more conservative rewrite
                # costs nothing).
                qs = qs.replace(b"?amp;", b"?").replace(b"&amp;", b"&")
                # If the literal first hop is the bare `amp;…` (browser
                # strips the `?` for us), handle that too.
                if qs.startswith(b"amp;"):
                    qs = qs[len(b"amp;") :]
                # Starlette's Scope is a MutableMapping[str, Any] in
                # the runtime path; coerce to a fresh dict so downstream
                # middlewares see a mutated copy rather than a shared
                # reference. mypy is happy with the resulting dict[str, Any].
                scope = dict(scope)
                scope["query_string"] = qs

        await self.app(scope, receive, send)


# Re-exported helper so `src.main` can wire the middleware without
# needing to import the class directly.
def install_amp_middleware(app: Any) -> None:
    """Convenience: `install_amp_middleware(fastapi_app)`."""
    app.add_middleware(AmpQueryParamMiddleware)


__all__ = ["AmpQueryParamMiddleware", "install_amp_middleware"]


# Type stubs to silence unused-import warnings in some IDEs.
_HandlerType = Callable[..., Awaitable[Any]]
