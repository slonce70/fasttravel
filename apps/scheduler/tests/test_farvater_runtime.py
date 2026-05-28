from __future__ import annotations

import importlib


def test_farvater_runtime_exposes_shared_catalog_countries_without_jobs_import() -> None:
    runtime = importlib.import_module("src.clients.farvater_runtime")

    assert ("turkey", "TR") in runtime.CATALOG_COUNTRIES


def test_catalog_and_sitemap_jobs_use_runtime_client_directly() -> None:
    runtime = importlib.import_module("src.clients.farvater_runtime")
    catalog_job = importlib.import_module("src.jobs.snapshot_catalog_farvater")
    sitemap_job = importlib.import_module("src.jobs.sitemap_long_tail")

    assert catalog_job.CATALOG_COUNTRIES is runtime.CATALOG_COUNTRIES
    assert catalog_job.open_farvater_client is runtime.open_farvater_client
    assert sitemap_job.CATALOG_COUNTRIES is runtime.CATALOG_COUNTRIES
    assert sitemap_job.open_farvater_client is runtime.open_farvater_client
