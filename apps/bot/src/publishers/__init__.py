"""Shared Telegram publisher library.

Exposes a minimal, stateless API for sending channel posts. Imported by
apps/scheduler/src/jobs/post_deals.py (vendored at image build time) and
by apps/bot/src/main.py once it gets fleshed out.
"""
from src.publishers.broadcast import (
    MARKDOWN_V2_ESCAPE_CHARS,
    broadcast_deal,
    escape_markdown_v2,
    make_bot,
)

__all__ = [
    "MARKDOWN_V2_ESCAPE_CHARS",
    "broadcast_deal",
    "escape_markdown_v2",
    "make_bot",
]
