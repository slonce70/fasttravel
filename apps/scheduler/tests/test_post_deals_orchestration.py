from __future__ import annotations

import importlib
from datetime import date
from types import SimpleNamespace

import pytest

post_deals_module = importlib.import_module("src.jobs.post_deals")
post_deals_job = post_deals_module.post_deals


def _settings(**overrides):
    values = {
        "telegram_enabled": True,
        "telegram_bot_token": "token",
        "telegram_channel_id": "-100123",
        "public_site_url": "https://fasttravel.test",
        "deals_daily_cap": 30,
        "deals_per_post_tick": 5,
        "telegram_send_delay_seconds": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _deal_row(deal_id: int, *, hotel_id: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        id=deal_id,
        hotel_id=hotel_id,
        discount_pct=19,
        hotel_name="Albatros Dana Beach Resort",
        hotel_slug="albatros-dana-beach-resort",
        stars=5,
        region_name="Хургада",
        country_name="Єгипет",
        check_in=date(2026, 6, 1),
        nights=9,
        meal_plan="AI",
        price_uah=104678,
        baseline_p50=128602,
        operator_display_name="Farvater",
        deep_link="https://farvater.travel/hotel/eg/albatros",
        detection_method="calendar_anomaly",
        description_uk=None,
        review_score=None,
        review_count=None,
    )


class _Result:
    def __init__(self, *, scalar=None, rows=None, rowcount: int = 1) -> None:
        self._scalar = scalar
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(
        self,
        rows,
        marked,
        *,
        lock_acquired: bool = True,
        mark_rowcount: int = 1,
    ) -> None:
        self._rows = rows
        self._marked = marked
        self._lock_acquired = lock_acquired
        self._mark_rowcount = mark_rowcount
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql, params=None):
        text = getattr(sql, "text", str(sql))
        if "pg_try_advisory_lock" in text:
            return _Result(scalar=self._lock_acquired)
        if "pg_advisory_unlock" in text:
            return _Result(scalar=True)
        if "SELECT COUNT(*) AS n" in text:
            return _Result(scalar=0)
        if "FROM deals d" in text:
            return _Result(rows=self._rows)
        if "RETURNING id" in text:
            return _Result(scalar=(params or {}).get("deal_id"))
        if "SET telegram_msg_id = NULL" in text:
            return _Result(scalar=None)
        if "SET posted_at = NOW()" in text:
            self._marked.append(dict(params or {}))
            return _Result(scalar=None, rowcount=self._mark_rowcount)
        raise AssertionError(f"unexpected SQL: {text[:120]}")

    async def commit(self):
        self.commits += 1


class _FakeBot:
    def __init__(self) -> None:
        self.session = SimpleNamespace(closed=False)

        async def close():
            self.session.closed = True

        self.session.close = close


@pytest.mark.asyncio
async def test_post_deals_disabled_telegram_does_not_touch_db_or_bot(monkeypatch) -> None:
    module = post_deals_module
    monkeypatch.setattr(module, "get_settings", lambda: _settings(telegram_enabled=False))
    monkeypatch.setattr(
        module,
        "async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("db should not be touched")),
    )
    monkeypatch.setattr(
        module,
        "make_bot",
        lambda _token: (_ for _ in ()).throw(AssertionError("bot should not be created")),
    )

    await post_deals_job()


@pytest.mark.asyncio
async def test_post_deals_existing_runner_skips_before_select_or_bot(monkeypatch) -> None:
    module = post_deals_module
    marked: list[dict] = []
    rows = [_deal_row(1)]

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        module,
        "async_session_factory",
        lambda: _FakeSession(rows, marked, lock_acquired=False),
    )
    monkeypatch.setattr(
        module,
        "make_bot",
        lambda _token: (_ for _ in ()).throw(AssertionError("bot should not be created")),
    )

    await post_deals_job()

    assert marked == []


@pytest.mark.asyncio
async def test_post_deals_all_send_failures_raise_and_do_not_mark(monkeypatch) -> None:
    module = post_deals_module
    marked: list[dict] = []
    bot = _FakeBot()
    rows = [_deal_row(1), _deal_row(2)]

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)

    async def fail_broadcast(_bot, _channel, _text):
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr(module, "broadcast_deal", fail_broadcast)

    with pytest.raises(RuntimeError, match="all Telegram sends failed"):
        await post_deals_job()

    assert marked == []
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_post_deals_partial_failure_marks_only_successes(monkeypatch) -> None:
    module = post_deals_module
    marked: list[dict] = []
    bot = _FakeBot()
    rows = [_deal_row(1), _deal_row(2)]

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)

    attempts = 0

    async def broadcast(_bot, _channel, text):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first send failed")
        return 777

    monkeypatch.setattr(module, "broadcast_deal", broadcast)

    await post_deals_job()

    assert marked == [{"msg_id": 777, "pending_msg_id": -1, "deal_id": 2}]
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_post_deals_uses_configured_public_hotel_url_when_operator_link_missing(
    monkeypatch,
) -> None:
    module = post_deals_module
    marked: list[dict] = []
    bot = _FakeBot()
    rows = [_deal_row(1)]
    rows[0].deep_link = None
    seen_texts: list[str] = []

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: _settings(public_site_url="https://channel.fasttravel.test/root/"),
    )
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)

    async def broadcast(_bot, _channel, text):
        seen_texts.append(text)
        return 777

    monkeypatch.setattr(module, "broadcast_deal", broadcast)

    await post_deals_job()

    assert marked == [{"msg_id": 777, "pending_msg_id": -1, "deal_id": 1}]
    assert (
        "(https://channel.fasttravel.test/root/hotels/albatros-dana-beach-resort)" in seen_texts[0]
    )
    assert "https://fasttravel.com.ua" not in seen_texts[0]


@pytest.mark.asyncio
async def test_post_deals_raises_when_successful_send_cannot_be_recorded(
    monkeypatch,
) -> None:
    module = post_deals_module
    marked: list[dict] = []
    bot = _FakeBot()
    rows = [_deal_row(1)]

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        module,
        "async_session_factory",
        lambda: _FakeSession(rows, marked, mark_rowcount=0),
    )
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)

    async def broadcast(_bot, _channel, _text):
        return 777

    monkeypatch.setattr(module, "broadcast_deal", broadcast)

    with pytest.raises(RuntimeError, match="Telegram send could not be recorded"):
        await post_deals_job()

    assert marked == [{"msg_id": 777, "pending_msg_id": -1, "deal_id": 1}]
    assert bot.session.closed is True
