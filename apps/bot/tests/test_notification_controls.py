"""Phase-2 notification controls: per-sub mute, global pause/resume, and the
profile notifications submenu.

DB-free: the bot test suite has no Postgres (every other test mocks the
session), so we drive the helpers against a fake session that records every
executed statement and returns scripted rows. We assert the CONTRACT:

  - mute/un-mute flips is_active via a chat_id-scoped UPDATE,
  - pause writes a {"pause": {...}} block into filters_jsonb (preserving
    other keys via the `||` merge) and only pauses currently-active subs,
  - resume reactivates ONLY the ids we paused and clears the pause key,
  - maybe_auto_resume expires a timed pause lazily (now >= until).

The callback tests mock the db helpers (not the session) and capture the
edited message + answered toast, mirroring test_profile / test_search_wizard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import src.handlers.profile as profile_mod
import src.handlers.subscribe as sub_mod
import src.infra.db as db_mod

# ---------------------------------------------------------------------------
# Fake session that records statements + returns scripted results.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, *, rows: list[tuple[Any, ...]] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def first(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _RecordingSession:
    """Captures (sql, params) for every execute; serves results from a
    callable keyed on the statement text so a single helper can issue several
    different statements in one transaction."""

    def __init__(self, responder) -> None:  # type: ignore[no-untyped-def]
        self._responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, sql, params=None):  # type: ignore[no-untyped-def]
        stmt = str(sql)
        self.calls.append((stmt, params or {}))
        return self._responder(stmt, params or {})

    async def commit(self) -> None:
        self.committed = True


def _install(monkeypatch, responder) -> _RecordingSession:  # type: ignore[no-untyped-def]
    session = _RecordingSession(responder)

    def _factory():  # type: ignore[no-untyped-def]
        return lambda: session

    monkeypatch.setattr(db_mod, "get_session_factory", _factory)
    return session


# ---------------------------------------------------------------------------
# set_subscription_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_subscription_active_scopes_by_chat_and_id(monkeypatch) -> None:
    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        return _Result(rowcount=1)

    session = _install(monkeypatch, responder)
    ok = await db_mod.set_subscription_active(123, 7, active=False)

    assert ok is True
    stmt, params = session.calls[0]
    assert "UPDATE telegram_subscriber_filters" in stmt
    assert "SET is_active = :active" in stmt
    assert "chat_id = :chat_id AND id = :id" in stmt
    assert params == {"active": False, "chat_id": 123, "id": 7}
    assert session.committed


@pytest.mark.asyncio
async def test_set_subscription_active_returns_false_when_no_row(monkeypatch) -> None:
    _install(monkeypatch, lambda stmt, params: _Result(rowcount=0))
    assert await db_mod.set_subscription_active(123, 999, active=True) is False


# ---------------------------------------------------------------------------
# pause_all_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_all_alerts_pauses_active_and_writes_block(monkeypatch) -> None:
    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        if "UPDATE telegram_subscriber_filters" in stmt:
            # The RETURNING id of the just-paused (active) subs.
            return _Result(rows=[(11,), (22,)], rowcount=2)
        return _Result()  # the filters_jsonb write

    session = _install(monkeypatch, responder)
    until = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    paused = await db_mod.pause_all_alerts(555, until)

    assert paused == [11, 22]
    # First statement: only the currently-active subs are paused.
    first_stmt, _ = session.calls[0]
    assert "SET is_active = false" in first_stmt
    assert "is_active = true" in first_stmt  # WHERE clause guard
    assert "RETURNING id" in first_stmt

    # Second statement: merge the pause block into filters_jsonb (preserve
    # other keys via `||`), with the paused ids + ISO until.
    jsonb_stmt, jsonb_params = session.calls[1]
    assert "filters_jsonb = filters_jsonb || CAST(:pause AS jsonb)" in jsonb_stmt
    import json as _json

    block = _json.loads(jsonb_params["pause"])
    assert block["pause"]["filter_ids"] == [11, 22]
    assert block["pause"]["until"] == until.isoformat()
    assert session.committed


@pytest.mark.asyncio
async def test_pause_all_alerts_forever_stores_null_until(monkeypatch) -> None:
    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        if "UPDATE telegram_subscriber_filters" in stmt:
            return _Result(rows=[(11,)], rowcount=1)
        return _Result()

    session = _install(monkeypatch, responder)
    paused = await db_mod.pause_all_alerts(555, None)

    assert paused == [11]
    import json as _json

    block = _json.loads(session.calls[1][1]["pause"])
    assert block["pause"]["until"] is None


# ---------------------------------------------------------------------------
# get_pause_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pause_state_returns_block(monkeypatch) -> None:
    prefs = {"pause": {"until": None, "filter_ids": [1, 2]}, "other": "keep"}
    _install(monkeypatch, lambda stmt, params: _Result(rows=[(prefs,)]))

    state = await db_mod.get_pause_state(555)
    assert state == {"until": None, "filter_ids": [1, 2]}


@pytest.mark.asyncio
async def test_get_pause_state_none_when_not_paused(monkeypatch) -> None:
    _install(monkeypatch, lambda stmt, params: _Result(rows=[({"other": "x"},)]))
    assert await db_mod.get_pause_state(555) is None


@pytest.mark.asyncio
async def test_get_pause_state_decodes_json_string(monkeypatch) -> None:
    """Defensive: if the JSONB codec ever returns a string, we still decode."""
    import json as _json

    raw = _json.dumps({"pause": {"until": None, "filter_ids": [9]}})
    _install(monkeypatch, lambda stmt, params: _Result(rows=[(raw,)]))

    assert await db_mod.get_pause_state(555) == {"until": None, "filter_ids": [9]}


# ---------------------------------------------------------------------------
# resume_all_alerts — reactivate only the ids WE paused.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_reactivates_only_paused_ids_and_clears_key(monkeypatch) -> None:
    prefs = {"pause": {"until": None, "filter_ids": [11, 22]}}

    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        if "SELECT filters_jsonb" in stmt:
            return _Result(rows=[(prefs,)])
        if "SET is_active = true" in stmt:
            return _Result(rowcount=2)
        return _Result()  # the `- 'pause'` clear

    session = _install(monkeypatch, responder)
    count = await db_mod.resume_all_alerts(555)

    assert count == 2
    reactivate = next(c for c in session.calls if "SET is_active = true" in c[0])
    # Only the ids we paused are reactivated (id = ANY(:ids)).
    assert "id = ANY(:ids)" in reactivate[0]
    assert reactivate[1]["ids"] == [11, 22]
    # The pause key is dropped (preserving any other prefs via `- 'pause'`).
    assert any("filters_jsonb - 'pause'" in c[0] for c in session.calls)
    assert session.committed


@pytest.mark.asyncio
async def test_resume_when_not_paused_is_noop_clear(monkeypatch) -> None:
    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        if "SELECT filters_jsonb" in stmt:
            return _Result(rows=[({},)])
        return _Result()

    session = _install(monkeypatch, responder)
    count = await db_mod.resume_all_alerts(555)

    assert count == 0
    # No reactivation statement issued when there were no paused ids.
    assert not any("SET is_active = true" in c[0] for c in session.calls)


# ---------------------------------------------------------------------------
# maybe_auto_resume — lazy expiry.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_auto_resume_expires_elapsed_timed_pause(monkeypatch) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    prefs = {"pause": {"until": past, "filter_ids": [11]}}

    def responder(stmt: str, params: dict[str, Any]) -> _Result:
        if "SELECT filters_jsonb" in stmt:
            return _Result(rows=[(prefs,)])
        if "SET is_active = true" in stmt:
            return _Result(rowcount=1)
        return _Result()

    session = _install(monkeypatch, responder)
    resumed = await db_mod.maybe_auto_resume(555)

    assert resumed is True
    assert any("SET is_active = true" in c[0] for c in session.calls)


@pytest.mark.asyncio
async def test_maybe_auto_resume_keeps_future_timed_pause(monkeypatch) -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    prefs = {"pause": {"until": future, "filter_ids": [11]}}
    session = _install(monkeypatch, lambda stmt, params: _Result(rows=[(prefs,)]))

    assert await db_mod.maybe_auto_resume(555) is False
    # Only the read happened — no resume UPDATE.
    assert all("SET is_active = true" not in c[0] for c in session.calls)


@pytest.mark.asyncio
async def test_maybe_auto_resume_never_expires_forever_pause(monkeypatch) -> None:
    prefs = {"pause": {"until": None, "filter_ids": [11]}}
    _install(monkeypatch, lambda stmt, params: _Result(rows=[(prefs,)]))
    assert await db_mod.maybe_auto_resume(555) is False


@pytest.mark.asyncio
async def test_maybe_auto_resume_false_when_not_paused(monkeypatch) -> None:
    _install(monkeypatch, lambda stmt, params: _Result(rows=[({},)]))
    assert await db_mod.maybe_auto_resume(555) is False


# ===========================================================================
# Callback handlers
# ===========================================================================


class _FakeUser:
    def __init__(self, user_id: int, first_name: str = "Іван") -> None:
        self.id = user_id
        self.first_name = first_name
        self.username = "ivan"


class _FakeMessage:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append({"text": text, **kwargs})

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.edits.append({"text": text, **kwargs})


class _FakeQuery:
    def __init__(self, data: str, message: _FakeMessage | None, user_id: int = 123) -> None:
        self.data = data
        self.message = message
        self.from_user = _FakeUser(user_id)
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


@pytest.fixture(autouse=True)
def _fake_callback_message(monkeypatch):
    """`callback_message` returns the message only if it's a real aiogram
    Message (isinstance guard). Our _FakeMessage isn't one, so patch the helper
    in both handler modules to pass our fake (or None) straight through — that
    lets the handler bodies run instead of short-circuiting on the guard."""

    def _passthrough(query):  # type: ignore[no-untyped-def]
        return query.message

    monkeypatch.setattr(sub_mod, "callback_message", _passthrough)
    monkeypatch.setattr(profile_mod, "callback_message", _passthrough)
    yield


# ---- subscribe: mute / un-mute -------------------------------------------


@pytest.mark.asyncio
async def test_cb_mute_flips_inactive_and_rerenders(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _set_active(chat_id: int, sub_id: int, active: bool) -> bool:
        captured["args"] = (chat_id, sub_id, active)
        return True

    async def _list(chat_id: int) -> list[dict[str, Any]]:
        return [{"id": 7, "country_iso2": "TR", "is_active": False}]

    monkeypatch.setattr(sub_mod, "set_subscription_active", _set_active)
    monkeypatch.setattr(sub_mod, "list_subscriptions", _list)

    msg = _FakeMessage()
    query = _FakeQuery("sub:mute:7", msg)
    await sub_mod.cb_mute(query)  # type: ignore[arg-type]

    assert captured["args"] == (123, 7, False)  # muting → active=False
    assert msg.edits, "expected the subs list to be re-rendered"
    # The re-rendered list shows the paused suffix for the now-inactive sub.
    assert "на паузі" in msg.edits[0]["text"]
    assert query.answers[0]["text"] == "Підписку призупинено"


@pytest.mark.asyncio
async def test_cb_unmute_sets_active_true(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _set_active(chat_id: int, sub_id: int, active: bool) -> bool:
        captured["args"] = (chat_id, sub_id, active)
        return True

    async def _list(chat_id: int) -> list[dict[str, Any]]:
        return [{"id": 7, "country_iso2": "TR", "is_active": True}]

    monkeypatch.setattr(sub_mod, "set_subscription_active", _set_active)
    monkeypatch.setattr(sub_mod, "list_subscriptions", _list)

    query = _FakeQuery("sub:on:7", _FakeMessage())
    await sub_mod.cb_unmute(query)  # type: ignore[arg-type]

    assert captured["args"] == (123, 7, True)
    assert query.answers[0]["text"] == "Підписку ввімкнено"


@pytest.mark.asyncio
async def test_cb_mute_from_alert_without_list_only_toasts(monkeypatch) -> None:
    """A mute tapped from a scheduler alert has no subs-list message to
    re-render (message=None) — it must not crash, just toast."""

    async def _set_active(chat_id: int, sub_id: int, active: bool) -> bool:
        return True

    monkeypatch.setattr(sub_mod, "set_subscription_active", _set_active)

    query = _FakeQuery("sub:mute:42", message=None)
    await sub_mod.cb_mute(query)  # type: ignore[arg-type]

    assert query.answers[0]["text"] == "Підписку призупинено"


@pytest.mark.asyncio
async def test_cb_mute_unknown_sub_answers_not_found(monkeypatch) -> None:
    async def _set_active(chat_id: int, sub_id: int, active: bool) -> bool:
        return False

    monkeypatch.setattr(sub_mod, "set_subscription_active", _set_active)

    query = _FakeQuery("sub:mute:999", _FakeMessage())
    await sub_mod.cb_mute(query)  # type: ignore[arg-type]

    assert query.answers[0]["text"] == "Не знайдено"


# ---- subscribe: keyboard shape -------------------------------------------


def test_subs_kb_active_sub_offers_mute_and_edit() -> None:
    kb = sub_mod._subs_kb([{"id": 7, "country_iso2": "TR", "is_active": True}])
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "sub:del:7" in cbs
    assert "sub:mute:7" in cbs  # active → offer mute
    assert "sub:on:7" not in cbs
    assert "sub:edit:7" in cbs
    assert "sub:add" in cbs


def test_subs_kb_inactive_sub_offers_unmute() -> None:
    kb = sub_mod._subs_kb([{"id": 7, "country_iso2": "TR", "is_active": False}])
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "sub:on:7" in cbs  # inactive → offer turn-on
    assert "sub:mute:7" not in cbs


def test_render_subscriptions_marks_paused_sub() -> None:
    body = sub_mod._render_subscriptions(
        [
            {"id": 1, "country_iso2": "TR", "is_active": True},
            {"id": 2, "country_iso2": "EG", "is_active": False},
        ]
    )
    # Exactly the inactive sub gets the paused suffix.
    assert "на паузі" in body
    assert body.count("на паузі") == 1


# ---- profile: notifications submenu --------------------------------------


def test_notif_kb_has_all_pause_buttons() -> None:
    cbs = [b.callback_data for row in profile_mod._notif_kb().inline_keyboard for b in row]
    assert {
        "prof:pause:24h",
        "prof:pause:7d",
        "prof:pause:forever",
        "prof:resume",
        "prof:back",
    } <= set(cbs)


def test_notif_state_line_renders_each_state() -> None:
    assert "увімкнені" in profile_mod._notif_state_line(None)
    assert "поки не ввімкнете" in profile_mod._notif_state_line({"until": None, "filter_ids": []})
    timed = profile_mod._notif_state_line({"until": "2026-06-04T12:00:00+00:00", "filter_ids": [1]})
    assert "На паузі до" in timed
    # MarkdownV2: the date's dot must be escaped, never a raw literal dot.
    assert "04\\." in timed or "\\." in timed


@pytest.mark.asyncio
async def test_cb_pause_24h_computes_until_and_rerenders(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _pause(chat_id: int, until: datetime | None) -> list[int]:
        captured["until"] = until
        return [1, 2]

    async def _get_pause_state(chat_id: int) -> dict[str, Any] | None:
        return {"until": (captured["until"]).isoformat(), "filter_ids": [1, 2]}

    monkeypatch.setattr(profile_mod, "pause_all_alerts", _pause)
    monkeypatch.setattr(profile_mod, "get_pause_state", _get_pause_state)

    msg = _FakeMessage()
    query = _FakeQuery("prof:pause:24h", msg)
    before = datetime.now(UTC)
    await profile_mod.cb_pause(query)  # type: ignore[arg-type]
    after = datetime.now(UTC)

    until = captured["until"]
    assert until is not None
    # ~24h from now (allow a small execution window).
    assert before + timedelta(hours=24) - timedelta(seconds=5) <= until
    assert until <= after + timedelta(hours=24) + timedelta(seconds=5)
    assert msg.edits, "submenu re-rendered after pause"
    assert query.answers[0]["text"] == "Пауза на 24 год"


@pytest.mark.asyncio
async def test_cb_pause_forever_passes_none(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _pause(chat_id: int, until: datetime | None) -> list[int]:
        captured["until"] = until
        return [1]

    async def _get_pause_state(chat_id: int) -> dict[str, Any] | None:
        return {"until": None, "filter_ids": [1]}

    monkeypatch.setattr(profile_mod, "pause_all_alerts", _pause)
    monkeypatch.setattr(profile_mod, "get_pause_state", _get_pause_state)

    query = _FakeQuery("prof:pause:forever", _FakeMessage())
    await profile_mod.cb_pause(query)  # type: ignore[arg-type]

    assert captured["until"] is None
    assert query.answers[0]["text"] == "Пауза до ввімкнення"


@pytest.mark.asyncio
async def test_cb_resume_reactivates_and_reports_count(monkeypatch) -> None:
    async def _resume(chat_id: int) -> int:
        return 3

    async def _get_pause_state(chat_id: int) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(profile_mod, "resume_all_alerts", _resume)
    monkeypatch.setattr(profile_mod, "get_pause_state", _get_pause_state)

    msg = _FakeMessage()
    query = _FakeQuery("prof:resume", msg)
    await profile_mod.cb_resume(query)  # type: ignore[arg-type]

    assert msg.edits
    assert query.answers[0]["text"] == "Відновлено: 3"


@pytest.mark.asyncio
async def test_cb_notif_runs_auto_resume_and_shows_state(monkeypatch) -> None:
    calls: list[str] = []

    async def _auto(chat_id: int) -> bool:
        calls.append("auto")
        return False

    async def _get_pause_state(chat_id: int) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(profile_mod, "maybe_auto_resume", _auto)
    monkeypatch.setattr(profile_mod, "get_pause_state", _get_pause_state)

    msg = _FakeMessage()
    query = _FakeQuery("prof:notif", msg)
    await profile_mod.cb_notif(query)  # type: ignore[arg-type]

    assert "auto" in calls  # lazy expiry checked on open
    assert msg.edits
    assert "Сповіщення" in msg.edits[0]["text"]
