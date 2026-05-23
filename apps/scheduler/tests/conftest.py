"""Shared pytest fixtures for scheduler tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Force asyncio for any anyio-based tests."""
    return "asyncio"
