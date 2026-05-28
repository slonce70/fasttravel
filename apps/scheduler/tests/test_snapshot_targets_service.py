from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.services.snapshot_targets import PRICE_REFRESH_TARGETS_SQL, path_from_slug, refresh_targets


def test_path_from_slug_reconstructs_farvater_hotel_url() -> None:
    assert path_from_slug("fv-tr-active-hotel") == "/uk/hotel/tr/active-hotel/"
    assert path_from_slug("other-tr-active-hotel") is None


async def test_refresh_targets_reprobes_decayed_previously_priced_hotels() -> None:
    class _Rows:
        def all(self):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=1,
                    canonical_slug="fv-tr-active-hotel",
                    country_iso2="TR",
                    external_id="101",
                    has_active_prices=True,
                    last_priced_at=date(2026, 5, 1),
                ),
                SimpleNamespace(
                    id=2,
                    canonical_slug="fv-tr-no-inventory",
                    country_iso2="TR",
                    external_id="102",
                    has_active_prices=False,
                    last_priced_at=date(2026, 5, 1),
                ),
                SimpleNamespace(
                    id=3,
                    canonical_slug="fv-eg-never-priced",
                    country_iso2="EG",
                    external_id="103",
                    has_active_prices=False,
                    last_priced_at=None,
                ),
            ]

    class _FakeSession:
        async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return _Rows()

    targets = await refresh_targets(_FakeSession(), ["TR", "EG"], None)

    assert targets == [
        ("/uk/hotel/tr/active-hotel/", "TR", 1, "101"),
        ("/uk/hotel/tr/no-inventory/", "TR", 2, "102"),
        ("/uk/hotel/eg/never-priced/", "EG", 3, "103"),
    ]


def test_refresh_targets_sql_cools_down_recent_unpriced_hotels() -> None:
    sql = PRICE_REFRESH_TARGETS_SQL.text

    assert "h.has_active_prices = TRUE" in sql
    assert "h.last_priced_at IS NULL" in sql
    assert "h.last_priced_at < NOW() - make_interval" in sql
    assert ":unpriced_cooldown_hours" in sql


async def test_refresh_targets_passes_default_unpriced_cooldown_param() -> None:
    seen_params: dict[str, object] = {}

    class _Rows:
        def all(self):  # type: ignore[no-untyped-def]
            return []

    class _FakeSession:
        async def execute(self, _sql, params):  # type: ignore[no-untyped-def]
            seen_params.update(params)
            return _Rows()

    await refresh_targets(_FakeSession(), ["TR"], None)

    assert seen_params["unpriced_cooldown_hours"] == 24
