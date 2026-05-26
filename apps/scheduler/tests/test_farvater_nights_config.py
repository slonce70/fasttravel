from __future__ import annotations

import importlib


def test_refresh_worker_uses_same_expanded_nights_as_snapshot() -> None:
    snapshot = importlib.import_module("src.jobs.snapshot_farvater")
    refresh_worker = importlib.import_module("src.jobs.refresh_worker")

    assert refresh_worker.NIGHTS == snapshot.NIGHTS == [7, 8, 9, 10, 11, 12, 13, 14]


def test_canary_uses_expanded_nights_for_calendar_probe() -> None:
    canary = importlib.import_module("src.jobs.canary_farvater_schema")

    assert canary.CALENDAR_NIGHTS == [7, 8, 9, 10, 11, 12, 13, 14]
