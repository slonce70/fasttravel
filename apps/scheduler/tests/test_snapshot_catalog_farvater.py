from __future__ import annotations

import importlib

import pytest

from src.jobs.snapshot_catalog_farvater import snapshot_catalog_farvater


def test_snapshot_catalog_uses_hotel_page_client_directly() -> None:
    from src.clients import farvater_hotel_page

    snapshot_catalog_farvater_module = importlib.import_module("src.jobs.snapshot_catalog_farvater")

    assert snapshot_catalog_farvater_module.fetch_hotel_meta is farvater_hotel_page.fetch_hotel_meta


class _FakeGauge:
    """Stand-in for LAST_SUCCESSFUL_SNAPSHOT capturing stamp attempts."""

    def __init__(self) -> None:
        self.stamped: list[dict] = []

    def labels(self, **kwargs):  # type: ignore[no-untyped-def]
        self.stamped.append(kwargs)
        return self

    def set(self, _value: float) -> None:
        return None


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeClientCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _wire_common(monkeypatch, module, recorded, *, list_country_hotels, process_hotel):  # type: ignore[no-untyped-def]
    async def fake_ensure_operator(_db):  # type: ignore[no-untyped-def]
        return 18

    async def fake_country_dest_id(_db, _iso2):  # type: ignore[no-untyped-def]
        return 7

    async def fake_record_run(
        _db,
        _operator_id,
        status,
        rows_inserted,
        *,
        error="",
        started_at=None,
    ):  # type: ignore[no-untyped-def]
        recorded.append((status, rows_inserted, error))

    gauge = _FakeGauge()
    metrics_module = importlib.import_module("src.infra.metrics")
    monkeypatch.setattr(metrics_module, "LAST_SUCCESSFUL_SNAPSHOT", gauge)
    monkeypatch.setattr(module, "CATALOG_COUNTRIES", [("turkey", "TR"), ("egypt", "EG")])
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(module, "open_farvater_client", lambda: _FakeClientCtx())
    monkeypatch.setattr(module, "ensure_operator", fake_ensure_operator)
    monkeypatch.setattr(module, "country_dest_id", fake_country_dest_id)
    monkeypatch.setattr(module, "list_country_hotels", list_country_hotels)
    monkeypatch.setattr(module, "_process_catalog_hotel", process_hotel)
    monkeypatch.setattr(module, "_record_run", fake_record_run)
    return gauge


@pytest.mark.asyncio
async def test_catalog_records_failed_and_keeps_gauge_when_all_countries_fail(
    monkeypatch,
) -> None:
    """Cloudflare 403 on every catalog page must record a failed run and
    leave the StaleCatalog staleness gauge alone so the alert can fire."""
    module = importlib.import_module("src.jobs.snapshot_catalog_farvater")
    recorded: list[tuple[str, int, str]] = []

    async def fake_list_country_hotels(_client, _slug):  # type: ignore[no-untyped-def]
        raise RuntimeError("403 blocked")

    async def fake_process_hotel(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("no hotels should be processed")

    gauge = _wire_common(
        monkeypatch,
        module,
        recorded,
        list_country_hotels=fake_list_country_hotels,
        process_hotel=fake_process_hotel,
    )

    seen = await snapshot_catalog_farvater()

    assert seen == 0
    assert recorded == [("failed", 0, "countries_failed=2/2; no_hotels_seen")]
    assert gauge.stamped == []


@pytest.mark.asyncio
async def test_catalog_records_failed_when_no_hotels_seen(monkeypatch) -> None:
    """A silent parser/layout regression (every country lists zero hotels)
    accomplishes nothing and must not count as a successful run."""
    module = importlib.import_module("src.jobs.snapshot_catalog_farvater")
    recorded: list[tuple[str, int, str]] = []

    async def fake_list_country_hotels(_client, _slug):  # type: ignore[no-untyped-def]
        return []

    async def fake_process_hotel(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("no hotels should be processed")

    gauge = _wire_common(
        monkeypatch,
        module,
        recorded,
        list_country_hotels=fake_list_country_hotels,
        process_hotel=fake_process_hotel,
    )

    seen = await snapshot_catalog_farvater()

    assert seen == 0
    assert recorded == [("failed", 0, "no_hotels_seen")]
    assert gauge.stamped == []


@pytest.mark.asyncio
async def test_catalog_records_partial_and_keeps_gauge_when_one_country_fails(
    monkeypatch,
) -> None:
    module = importlib.import_module("src.jobs.snapshot_catalog_farvater")
    recorded: list[tuple[str, int, str]] = []

    async def fake_list_country_hotels(_client, slug):  # type: ignore[no-untyped-def]
        if slug == "egypt":
            raise RuntimeError("timeout")
        return ["/uk/hotel/tr/one/", "/uk/hotel/tr/two/"]

    async def fake_process_hotel(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return 1

    gauge = _wire_common(
        monkeypatch,
        module,
        recorded,
        list_country_hotels=fake_list_country_hotels,
        process_hotel=fake_process_hotel,
    )

    seen = await snapshot_catalog_farvater()

    assert seen == 2
    assert recorded == [("partial", 2, "countries_failed=1/2")]
    assert gauge.stamped == []


@pytest.mark.asyncio
async def test_catalog_clean_run_records_success_and_stamps_gauge(monkeypatch) -> None:
    module = importlib.import_module("src.jobs.snapshot_catalog_farvater")
    recorded: list[tuple[str, int, str]] = []

    async def fake_list_country_hotels(_client, _slug):  # type: ignore[no-untyped-def]
        return ["/uk/hotel/xx/one/", "/uk/hotel/xx/two/"]

    async def fake_process_hotel(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return 1

    gauge = _wire_common(
        monkeypatch,
        module,
        recorded,
        list_country_hotels=fake_list_country_hotels,
        process_hotel=fake_process_hotel,
    )

    seen = await snapshot_catalog_farvater()

    assert seen == 4
    assert recorded == [("success", 4, "")]
    assert gauge.stamped == [{"scheduled_job": "snapshot_catalog_farvater"}]
