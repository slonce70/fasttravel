from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from src.services.scrape_runs import record_scrape_run


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    async def execute(self, sql: Any, params: dict[str, Any]) -> None:
        self.calls.append((str(sql), params))

    async def commit(self) -> None:
        self.commits += 1


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def test_record_scrape_run_writes_common_shape_with_nullable_operator() -> None:
    db = _FakeSession()
    started_at = datetime(2026, 5, 28, 5, 0, tzinfo=UTC)

    await record_scrape_run(
        db,
        source="farvater_scrape",
        status="success",
        rows_inserted=17,
        operator_id=18,
        started_at=started_at,
    )

    sql, params = db.calls[0]
    assert "(started_at, finished_at, operator_id, source, status," in sql
    assert "VALUES (:s, NOW(), :op, :src, :st, :n, :e)" in sql
    assert params == {
        "s": started_at,
        "op": 18,
        "src": "farvater_scrape",
        "st": "success",
        "n": 17,
        "e": "",
    }


async def test_record_scrape_run_truncates_errors_and_allows_missing_operator() -> None:
    db = _FakeSession()

    await record_scrape_run(
        db,
        source="sitemap_long_tail",
        status="failed",
        rows_inserted=0,
        error="x" * 600,
    )

    _sql, params = db.calls[0]
    assert params["op"] is None
    assert params["src"] == "sitemap_long_tail"
    assert params["e"] == "x" * 500
    assert params["s"].tzinfo is UTC


@pytest.mark.asyncio
async def test_job_record_wrappers_delegate_to_shared_scrape_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 5, 28, 5, 0, tzinfo=UTC)
    calls: list[dict[str, Any]] = []

    async def _record_scrape_run(_db: _FakeSession, **kwargs: Any) -> None:
        calls.append(kwargs)

    cases: list[tuple[str, Callable[[Any], Awaitable[None]], dict[str, Any]]] = [
        (
            "src.jobs.refresh_baselines",
            lambda module: module._record_run(started_at, "failed", "baseline error"),
            {
                "source": "refresh_baselines",
                "status": "failed",
                "rows_inserted": 0,
                "error": "baseline error",
                "started_at": started_at,
            },
        ),
        (
            "src.jobs.decay_active_prices",
            lambda module: module._record_run(started_at, "success", 7),
            {
                "source": "decay_active_prices",
                "status": "success",
                "rows_inserted": 7,
                "error": "",
                "started_at": started_at,
            },
        ),
        (
            "src.jobs.canary_farvater_schema",
            lambda module: module._record_run(started_at, "failed", "schema error"),
            {
                "source": "canary_farvater_schema",
                "status": "failed",
                "rows_inserted": 0,
                "error": "schema error",
                "started_at": started_at,
            },
        ),
        (
            "src.jobs.sitemap_long_tail",
            lambda module: module._record_sitemap_run(
                "failed",
                rows=3,
                error="sitemap error",
                started_at=started_at,
            ),
            {
                "source": "sitemap_long_tail",
                "status": "failed",
                "rows_inserted": 3,
                "error": "sitemap error",
                "started_at": started_at,
            },
        ),
    ]

    for module_name, call, expected in cases:
        module = importlib.import_module(module_name)
        session = _FakeSession()
        monkeypatch.setattr(
            module,
            "async_session_factory",
            lambda session=session: _FakeSessionFactory(session),
        )
        monkeypatch.setattr(module, "record_scrape_run", _record_scrape_run, raising=False)

        await call(module)

        assert calls[-1] == expected
        assert session.calls == []
