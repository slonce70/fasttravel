"""pytest fixtures for the bot test suite.

Heavy-handed: every test gets its own metrics registry reset and FSM
storage so a previous test's counters / state can't leak in.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_module_globals(monkeypatch):
    """Reset module-level singletons that handlers reach for. Without
    this the api_client / db engine cached at the first import would
    survive the whole pytest session — fine in prod but trips tests
    that pass a mock URL via env."""
    import src.infra.api_client as api_client
    import src.infra.db as db_mod

    monkeypatch.setattr(api_client, "_CLIENT", None)
    monkeypatch.setattr(db_mod, "_ENGINE", None)
    monkeypatch.setattr(db_mod, "_SESSIONMAKER", None)
    yield
