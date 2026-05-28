from __future__ import annotations

from shared.publishers.broadcast import escape_markdown_v2_url


def test_escape_markdown_v2_url_escapes_link_destination_breakers() -> None:
    assert escape_markdown_v2_url(r"https://example.test/hotel/(nice)\deal") == (
        r"https://example.test/hotel/(nice\)\\deal"
    )


def test_escape_markdown_v2_url_handles_empty_values() -> None:
    assert escape_markdown_v2_url(None) == ""
    assert escape_markdown_v2_url("") == ""
