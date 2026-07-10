"""Regression tests for the shared Redis client factory defaults.

A client without socket_timeout waits forever on a half-open TCP
connection, which silently kills the BRPOP-based refresh worker and
hangs breaker/cap checks inside farvater jobs. These tests pin the
connection kwargs so the defaults can't regress.
"""

from __future__ import annotations

from shared.infra.redis_client import get_redis_factory
from src.jobs.refresh_worker import BRPOP_TIMEOUT_S


def _connection_kwargs() -> dict:
    # from_url builds the pool lazily — no sockets are opened here.
    client = get_redis_factory("redis://localhost:6379/0")()
    return client.connection_pool.connection_kwargs


def test_factory_bounds_socket_reads_and_health_checks() -> None:
    kwargs = _connection_kwargs()

    assert kwargs["socket_timeout"] == 10
    assert kwargs["socket_connect_timeout"] == 3
    assert kwargs["health_check_interval"] == 30


def test_socket_timeout_exceeds_brpop_blocking_window() -> None:
    """redis-py applies socket_timeout to the entire reply wait, including
    the server-side BRPOP block — the read bound must stay above the
    worker's blocking timeout or every idle poll raises TimeoutError."""
    kwargs = _connection_kwargs()

    assert kwargs["socket_timeout"] > BRPOP_TIMEOUT_S
