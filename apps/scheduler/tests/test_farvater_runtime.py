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


def test_prod_tier_config_uses_default_concurrency_when_http_env_unset(monkeypatch) -> None:
    runtime = importlib.import_module("src.clients.farvater_runtime")
    monkeypatch.delenv("FT_FARVATER_HTTP_CONCURRENCY", raising=False)
    monkeypatch.delenv("FT_FARVATER_DAILY_CAP", raising=False)
    monkeypatch.delenv("FT_FARVATER_HTTP_TIMEOUT_S", raising=False)

    config = runtime.prod_tier_config(default_concurrency=7)

    assert config.concurrency == 7
    assert config.daily_cap == 0
    assert config.timeout_s == 30.0


def test_prod_tier_config_http_concurrency_env_overrides_default(monkeypatch) -> None:
    runtime = importlib.import_module("src.clients.farvater_runtime")
    monkeypatch.setenv("FT_FARVATER_HTTP_CONCURRENCY", "11")

    config = runtime.prod_tier_config(default_concurrency=7)

    assert config.concurrency == 11


def test_prod_tier_config_falls_back_on_empty_or_invalid_env(monkeypatch) -> None:
    """An empty or non-numeric value in .env must not raise inside farvater
    jobs — prod_tier_config is evaluated lazily on every job run, so a bare
    int()/float() would fail every snapshot until the env is fixed."""
    runtime = importlib.import_module("src.clients.farvater_runtime")
    monkeypatch.setenv("FT_FARVATER_HTTP_CONCURRENCY", "many")
    monkeypatch.setenv("FT_FARVATER_HTTP_MIN_INTERVAL_S", "")
    monkeypatch.setenv("FT_FARVATER_DAILY_CAP", "")
    monkeypatch.setenv("FT_FARVATER_HTTP_TIMEOUT_S", "30s")

    config = runtime.prod_tier_config(default_concurrency=7)

    assert config.concurrency == 7
    assert config.min_interval_s == runtime.DEFAULT_MIN_INTERVAL_S
    assert config.daily_cap == 0
    assert config.timeout_s == 30.0
