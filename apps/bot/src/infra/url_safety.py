"""URL validation helpers for Telegram URL buttons."""

from __future__ import annotations

from urllib.parse import urlparse


def safe_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def is_http_url(value: object) -> bool:
    return safe_http_url(value) is not None
