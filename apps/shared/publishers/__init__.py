"""Shared Telegram publisher library.

Exposes a minimal, stateless API for sending channel posts. Imported by
apps/scheduler/src/jobs/post_deals.py and apps/bot/src/main.py — both
mount this package at /app/shared/ via Docker COPY at build time.
"""

from shared.publishers.broadcast import (
    MARKDOWN_V2_ESCAPE_CHARS,
    broadcast_deal,
    escape_markdown_v2,
    escape_markdown_v2_code,
    escape_markdown_v2_url,
    make_bot,
)

__all__ = [
    "MARKDOWN_V2_ESCAPE_CHARS",
    "broadcast_deal",
    "escape_markdown_v2",
    "escape_markdown_v2_code",
    "escape_markdown_v2_url",
    "make_bot",
]
