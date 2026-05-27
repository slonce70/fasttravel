from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.jobs.notify_subscribers import _render


def test_render_peer_anomaly_uses_neighboring_hotels_copy_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=28,
        hotel_name_uk="Peer Resort",
        hotel_stars=4,
        destination_name="Анталія",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=45500,
        detection_method="peer_anomaly",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Варіант за вашою підпискою" in out
    assert "дешевше за схожі готелі" in out
    assert "орієнтир схожих" in out
    assert "економія" not in out
    assert "~45 500 ₴~" not in out
