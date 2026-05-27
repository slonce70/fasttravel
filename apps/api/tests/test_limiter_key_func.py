"""Per-IP keying for slowapi behind nginx / Cloudflare.

The audit caught that the previous limiter used slowapi's stock
`get_remote_address`, which reads only `request.client.host`. Behind a
reverse proxy that means every request looks like it came from the
nginx-egress IP and a `10/hour` cap becomes effectively a global cap.

These tests exercise the resolver directly (no FastAPI app needed) so
they stay fast and don't depend on a live proxy.
"""

from __future__ import annotations

from src.infra.limiter import _client_ip


class _FakeClient:
    def __init__(self, host: str | None) -> None:
        self.host = host


class _FakeRequest:
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        client_host: str | None = "127.0.0.1",
    ) -> None:
        self.headers = headers or {}
        self.client = _FakeClient(client_host) if client_host else None


def test_prefers_cf_connecting_ip() -> None:
    req = _FakeRequest(
        headers={
            "CF-Connecting-IP": "203.0.113.4",
            "X-Forwarded-For": "10.0.0.1",
        },
    )
    assert _client_ip(req) == "203.0.113.4"


def test_falls_back_to_xff_when_cf_missing() -> None:
    req = _FakeRequest(headers={"X-Forwarded-For": "198.51.100.7, 172.20.0.1"})
    assert _client_ip(req) == "198.51.100.7"


def test_falls_back_to_client_host_when_no_proxy_headers() -> None:
    req = _FakeRequest(client_host="172.20.0.42")
    assert _client_ip(req) == "172.20.0.42"


def test_unknown_when_no_signal_available() -> None:
    req = _FakeRequest(client_host=None)
    assert _client_ip(req) == "unknown"


def test_empty_proxy_header_ignored() -> None:
    """Empty CF-Connecting-IP must not bucket every empty-header request
    together — fall through to XFF / client.host."""
    req = _FakeRequest(
        headers={"CF-Connecting-IP": "  ", "X-Forwarded-For": "203.0.113.99"},
    )
    assert _client_ip(req) == "203.0.113.99"


def test_xff_strips_whitespace() -> None:
    req = _FakeRequest(headers={"X-Forwarded-For": "  203.0.113.10 ,  10.0.0.1"})
    assert _client_ip(req) == "203.0.113.10"


def test_trusted_header_env_override(monkeypatch) -> None:
    """Operator can swap header priority via env var without code changes."""
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_HEADER", "X-Real-IP,X-Forwarded-For")
    req = _FakeRequest(
        headers={
            "CF-Connecting-IP": "203.0.113.1",  # ignored — not in trusted list
            "X-Real-IP": "192.0.2.55",
            "X-Forwarded-For": "10.0.0.1",
        },
    )
    assert _client_ip(req) == "192.0.2.55"
