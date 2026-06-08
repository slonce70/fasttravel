"""Telegram MarkdownV2 message-size helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence

TELEGRAM_MESSAGE_LIMIT = 4096
DEFAULT_PARSED_LIMIT = 3800

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def telegram_parsed_len(text: str) -> int:
    """Estimate Telegram's parsed MarkdownV2 length in UTF-16 code units."""
    stripped = _LINK_RE.sub(r"\1", text)
    stripped = stripped.replace("\\", "").replace("*", "")
    return len(stripped.encode("utf-16-le")) // 2


def _join_message(
    header: str,
    blocks: Sequence[str],
    footer: str | None,
    separator: str,
) -> str:
    parts: list[str] = []
    if header:
        parts.append(header)
    if blocks:
        body = separator.join(blocks)
        parts.append(body)
    if footer:
        parts.append(footer)
    return "\n\n".join(parts)


def fit_markdown_v2_message(
    header: str,
    blocks: Sequence[str],
    footer: str | None,
    separator: str,
    *,
    max_parsed_len: int = DEFAULT_PARSED_LIMIT,
) -> str:
    """Return a whole-block MarkdownV2 message within the parsed length budget.

    The footer is an overflow marker, so it is added only when at least one
    block is omitted. If header + footer alone exceed the budget, the shortest
    possible overflow message is returned; callers should keep those strings
    small enough for Telegram.
    """
    full = _join_message(header, blocks, None, separator)
    if telegram_parsed_len(full) <= max_parsed_len:
        return full

    shown: list[str] = []
    for block in blocks:
        candidate = _join_message(header, [*shown, block], footer, separator)
        if telegram_parsed_len(candidate) > max_parsed_len:
            break
        shown.append(block)

    return _join_message(header, shown, footer, separator)
