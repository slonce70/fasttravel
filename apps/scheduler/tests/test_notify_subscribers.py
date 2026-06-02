from __future__ import annotations

import importlib
from datetime import date
from types import SimpleNamespace

import pytest

from src.jobs.notify_subscribers import _notify_subscribers_locked, _render


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


def test_render_calendar_anomaly_shows_local_typical_strikethrough() -> None:
    # The date-dip baseline is the local typical price for these dates. Show it
    # struck-through ("звичайна ціна ~X~") so the card answers "cheaper than
    # what?" — but never as a fake "економія"/"save by buying now" claim.
    row = SimpleNamespace(
        discount_pct=19,
        hotel_name_uk="Albatros Dana Beach Resort",
        hotel_stars=5,
        destination_name="Хургада",
        country_name="Єгипет",
        check_in=date(2026, 6, 1),
        nights=9,
        meal_plan="AI",
        price_uah=104678,
        baseline_p50=128602,
        detection_method="calendar_anomaly",
        country_iso2="EG",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Цікава дата за вашою підпискою" in out
    assert "дешевше за сусідні дати" in out
    assert "звичайна ціна ~128 602 ₴~" in out
    assert "у середньому" not in out
    assert "економія" not in out


def test_render_includes_rating_and_description_when_present() -> None:
    row = SimpleNamespace(
        discount_pct=19,
        hotel_name_uk="Blue Istanbul Hotel",
        hotel_stars=4,
        destination_name="Стамбул",
        country_name="Туреччина",
        check_in=date(2026, 6, 13),
        nights=7,
        meal_plan="RO",
        price_uah=27401,
        baseline_p50=38389,
        detection_method="calendar_anomaly",
        country_iso2="TR",
        review_score=8.6,
        review_count=412,
        description_uk="Сучасний готель у центрі Стамбула, поряд із Блакитною мечеттю.",
    )

    out = _render(row, "https://fasttravel.test")

    assert "⭐ 8\\.6/10" in out
    assert "відгук" in out  # review-count word (declined form)
    assert "Сучасний готель у центрі Стамбула" in out


def test_render_percentile_uses_same_hotel_baseline_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=18,
        hotel_name_uk="Historical Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=39000,
        detection_method="percentile",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "нижча за звичайну" in out
    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out


def test_render_promo_discount_uses_operator_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=37,
        hotel_name_uk="Promo Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=21000,
        baseline_p50=33500,
        detection_method="promo_discount",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Знижка за вашою підпискою" in out
    assert "економія 12 500 ₴" in out
    assert "~33 500 ₴~" in out
    assert "Спецціна від оператора" in out


def test_render_unknown_method_uses_neutral_baseline_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=18,
        hotel_name_uk="Mystery Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=39000,
        detection_method="legacy_experiment",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out
    assert "нижча за звичайну" not in out


@pytest.mark.asyncio
async def test_sent_but_unrecorded_alert_logs_distinct_warning_not_failed(monkeypatch) -> None:
    """A successful send whose ledger write fails must NOT count as 'failed'.

    The message was delivered, so sent stays incremented and the run logs a
    DISTINCT `mark_notified_failed` warning (the duplicate-alert risk) rather
    than folding it into the generic 'failed' bucket — which would
    double-count the row (sent+1 then failed+1) and skew the completion log.
    """
    module = importlib.import_module("src.jobs.notify_subscribers")

    # One matching row; reuse a known-good _render shape so rendering can't
    # be the thing that fails, then add the fields the send/mark loop reads.
    row = SimpleNamespace(
        discount_pct=37,
        hotel_name_uk="Promo Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=21000,
        baseline_p50=33500,
        detection_method="promo_discount",
        country_iso2="TR",
        chat_id=555,
        filter_id=42,
        deal_id=9001,
        deep_link="https://example.test/affiliate?h=1",
        hotel_slug="promo-resort-tr",
    )

    class _MatchResult:
        def all(self):  # type: ignore[no-untyped-def]
            return [row]

    class _Session:
        """Returns the match row; raises only on the _MARK_NOTIFIED write."""

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def execute(self, sql, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            statement = str(sql)
            # Discriminate on the INSERT (not the bare table name), because
            # the match query references telegram_filter_notifications inside
            # a NOT EXISTS too.
            if "INSERT INTO telegram_filter_notifications" in statement:
                raise RuntimeError("ledger write failed after a successful send")
            return _MatchResult()

        async def commit(self) -> None:
            return None

    class _FakeBotSession:
        async def close(self) -> None:
            return None

    class _FakeBot:
        def __init__(self) -> None:
            self.session = _FakeBotSession()
            self.sends = 0

        async def send_message(self, **_kwargs):  # type: ignore[no-untyped-def]
            self.sends += 1
            return SimpleNamespace(message_id=1)

    fake_bot = _FakeBot()

    events: list[tuple[str, dict]] = []

    class _FakeLog:
        def info(self, event: str, **kwargs):  # type: ignore[no-untyped-def]
            events.append((event, kwargs))

        def warning(self, event: str, **kwargs):  # type: ignore[no-untyped-def]
            events.append((event, kwargs))

    monkeypatch.setattr(module, "async_session_factory", lambda: _Session())
    monkeypatch.setattr(module, "make_bot", lambda _token: fake_bot)
    monkeypatch.setattr(module, "log", _FakeLog())
    monkeypatch.setattr(module, "SEND_DELAY_S", 0.0)

    settings = SimpleNamespace(telegram_bot_token="x", public_site_url="https://fasttravel.test")

    sent = await _notify_subscribers_locked(settings)

    # Message delivered exactly once and counted as sent.
    assert fake_bot.sends == 1
    assert sent == 1

    warnings_logged = {event for event, _ in events}
    # The ledger-write failure is its own distinct warning...
    assert "notify_subscribers.mark_notified_failed" in warnings_logged
    # ...and is NOT folded into the generic send-failed bucket.
    assert "notify_subscribers.send_failed" not in warnings_logged

    completed = [kwargs for event, kwargs in events if event == "notify_subscribers.completed"]
    assert completed, "expected a completion log line"
    assert completed[0]["sent"] == 1
    # The unrecorded-but-sent row must not double-count into 'failed'.
    assert completed[0]["failed"] == 0
