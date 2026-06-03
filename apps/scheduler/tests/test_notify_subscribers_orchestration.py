from __future__ import annotations

import importlib
from datetime import date
from types import SimpleNamespace

import pytest

notify_module = importlib.import_module("src.jobs.notify_subscribers")
notify_subscribers = notify_module.notify_subscribers


def _settings(**overrides):
    values = {
        "telegram_bot_token": "token",
        "public_site_url": "https://fasttravel.test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _alert_row(deal_id: int, *, filter_id: int = 10, chat_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        filter_id=filter_id,
        chat_id=chat_id,
        country_iso2="EG",
        deal_id=deal_id,
        hotel_id=100,
        check_in=date(2026, 6, 1),
        nights=9,
        meal_plan="AI",
        discount_pct=19,
        price_uah=104678,
        baseline_p50=128602,
        deep_link="https://farvater.travel/hotel/eg/albatros",
        detection_method="calendar_anomaly",
        hotel_name_uk="Albatros Dana Beach Resort",
        hotel_slug="albatros-dana-beach",
        hotel_stars=5,
        destination_name="Хургада",
        country_name="Єгипет",
    )


class _Result:
    def __init__(self, *, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows, marked, *, lock_acquired: bool = True) -> None:
        self._rows = rows
        self._marked = marked
        self._lock_acquired = lock_acquired
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
        if "FROM telegram_subscriber_filters" in text:
            return _Result(rows=self._rows)
        if "telegram_filter_notifications" in text:
            self._marked.append(dict(params or {}))
            return _Result()
        raise AssertionError(f"unexpected SQL: {text[:120]}")

    async def commit(self):
        self.commits += 1


class _FakeBot:
    def __init__(self, *, fail_all: bool = False, fail_first: bool = False) -> None:
        self.fail_all = fail_all
        self.fail_first = fail_first
        self.messages: list[dict] = []
        self.session = SimpleNamespace(closed=False)

        async def close():
            self.session.closed = True

        self.session.close = close

    async def send_message(self, **kwargs):
        if self.fail_all:
            raise RuntimeError("telegram unavailable")
        if self.fail_first and not self.messages:
            self.messages.append(kwargs)
            raise RuntimeError("first send failed")
        self.messages.append(kwargs)


@pytest.mark.asyncio
async def test_notify_subscribers_disabled_token_does_not_touch_db_or_bot(monkeypatch) -> None:
    module = notify_module
    monkeypatch.setattr(module, "get_settings", lambda: _settings(telegram_bot_token=None))
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

    assert await notify_subscribers() == 0


@pytest.mark.asyncio
async def test_notify_subscribers_existing_runner_skips_before_select_or_bot(monkeypatch) -> None:
    module = notify_module
    marked: list[dict] = []
    rows = [_alert_row(1)]

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

    assert await notify_subscribers() == 0
    assert marked == []


@pytest.mark.asyncio
async def test_notify_subscribers_all_send_failures_raise_and_do_not_mark(
    monkeypatch,
) -> None:
    module = notify_module
    marked: list[dict] = []
    rows = [_alert_row(1), _alert_row(2, filter_id=11, chat_id=456)]
    bot = _FakeBot(fail_all=True)

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)

    with pytest.raises(RuntimeError, match="all Telegram subscriber alerts failed"):
        await notify_subscribers()

    assert marked == []
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_notify_subscribers_partial_failure_marks_only_successes(monkeypatch) -> None:
    module = notify_module
    marked: list[dict] = []
    rows = [_alert_row(1), _alert_row(2, filter_id=11, chat_id=456)]
    bot = _FakeBot(fail_first=True)

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)
    monkeypatch.setattr(module.asyncio, "sleep", lambda _seconds: _noop_sleep())

    assert await notify_subscribers() == 1
    assert marked == [{"deal_id": 2, "filter_id": 11}]
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_alert_keyboard_carries_mute_button_for_this_filter(monkeypatch) -> None:
    """Phase-2 bot redesign appends a «🔕 Призупинити цю підписку» button
    (callback sub:mute:{filter_id}) to the alert keyboard — keyboard-only, so
    selection/marking are unchanged: still exactly one ledger mark per sent
    row, and the delete button stays."""
    module = notify_module
    marked: list[dict] = []
    rows = [_alert_row(1, filter_id=77)]
    bot = _FakeBot()

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(rows, marked))
    monkeypatch.setattr(module, "make_bot", lambda _token: bot)
    monkeypatch.setattr(module.asyncio, "sleep", lambda _seconds: _noop_sleep())

    assert await notify_subscribers() == 1
    # Selection/marking untouched: one mark for the one matched/sent row.
    assert marked == [{"deal_id": 1, "filter_id": 77}]

    kb = bot.messages[0]["reply_markup"]
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "sub:mute:77" in cbs  # mute THIS subscription from the alert
    assert "sub:del:77" in cbs  # existing delete button preserved


async def _noop_sleep() -> None:
    return None
