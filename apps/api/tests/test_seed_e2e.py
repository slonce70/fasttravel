from __future__ import annotations

import pytest

from scripts import seed_e2e


def test_seed_e2e_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FASTTRAVEL_ALLOW_E2E_SEED", raising=False)

    with pytest.raises(SystemExit, match="FASTTRAVEL_ALLOW_E2E_SEED=1"):
        seed_e2e.ensure_e2e_seed_allowed(cleanup=False)


def test_seed_e2e_refuses_production_even_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FASTTRAVEL_ALLOW_E2E_SEED", "1")
    monkeypatch.setenv("ENVIRONMENT", "prod")

    with pytest.raises(SystemExit, match="refusing to seed production"):
        seed_e2e.ensure_e2e_seed_allowed(cleanup=False)


def test_seed_e2e_cleanup_is_allowed_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FASTTRAVEL_ALLOW_E2E_SEED", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")

    seed_e2e.ensure_e2e_seed_allowed(cleanup=True)
