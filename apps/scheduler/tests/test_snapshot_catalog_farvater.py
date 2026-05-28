from __future__ import annotations

import importlib


def test_snapshot_catalog_uses_hotel_page_client_directly() -> None:
    from src.clients import farvater_hotel_page

    snapshot_catalog_farvater = importlib.import_module("src.jobs.snapshot_catalog_farvater")

    assert snapshot_catalog_farvater.fetch_hotel_meta is farvater_hotel_page.fetch_hotel_meta
