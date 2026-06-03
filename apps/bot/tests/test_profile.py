"""Tests for the /profile account hub and its /settings alias.

DB-free: the hub touches the DB (ensure_subscriber, list_subscriptions,
get_last_notification), so we monkeypatch those helpers and capture the
rendered message instead of standing up Postgres. We assert STRUCTURE
(keyboard buttons, presence of the active-subs / last-alert lines), not
exact copy, so chrome wording can change without breaking these.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import src.handlers.commands as commands_mod
import src.handlers.profile as profile_mod
from src.handlers.profile import _profile_kb


class _FakeUser:
    def __init__(self, user_id: int, first_name: str, username: str | None) -> None:
        self.id = user_id
        self.first_name = first_name
        self.username = username


class _FakeMessage:
    """Captures the text + reply_markup of the single answer() the hub sends."""

    def __init__(self, user: _FakeUser | None) -> None:
        self.from_user = user
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


def _patch_db(monkeypatch, *, subs: list[dict[str, Any]], last_alert: datetime | None) -> None:
    async def _ensure_subscriber(chat_id: int, username: str | None = None) -> None:
        return None

    async def _list_subscriptions(chat_id: int) -> list[dict[str, Any]]:
        return subs

    async def _get_last_notification(chat_id: int) -> datetime | None:
        return last_alert

    async def _maybe_auto_resume(chat_id: int) -> bool:
        return False

    monkeypatch.setattr(profile_mod, "ensure_subscriber", _ensure_subscriber)
    monkeypatch.setattr(profile_mod, "list_subscriptions", _list_subscriptions)
    monkeypatch.setattr(profile_mod, "get_last_notification", _get_last_notification)
    monkeypatch.setattr(profile_mod, "maybe_auto_resume", _maybe_auto_resume)


def test_profile_kb_buttons_all_work() -> None:
    """Every hub button is a working entrypoint — the callbacks the profile
    router handles (subs, notifications, delete), plus a real channel URL (no
    dead ends). Phase 2 adds the «⏸ Сповіщення» (prof:notif) toggle."""
    kb = _profile_kb()
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]

    assert "prof:subs" in callbacks
    assert "prof:notif" in callbacks  # notifications submenu (global pause)
    assert "prof:delete" in callbacks
    # Channel button is a working URL (reuses settings.public_channel_link).
    assert any(u and u.startswith("http") for u in urls)
    # «⏸ Сповіщення» sits between «Мої підписки» and «Видалити».
    notif_idx = callbacks.index("prof:notif")
    assert callbacks.index("prof:subs") < notif_idx < callbacks.index("prof:delete")


@pytest.mark.asyncio
async def test_show_profile_renders_active_subs_count(monkeypatch) -> None:
    _patch_db(
        monkeypatch,
        subs=[{"id": 1, "country_iso2": "TR"}, {"id": 2, "country_iso2": "EG"}],
        last_alert=None,
    )
    message = _FakeMessage(_FakeUser(123, "Іван", "ivan"))

    await profile_mod.show_profile(message)  # type: ignore[arg-type]

    assert len(message.answers) == 1
    body = message.answers[0]["text"]
    assert "Активних підписок: *2*" in body
    # No alert ever → no last-alert line (never render an empty / None date).
    assert "Останній алерт" not in body
    assert message.answers[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_show_profile_shows_last_alert_when_present(monkeypatch) -> None:
    _patch_db(
        monkeypatch,
        subs=[{"id": 1, "country_iso2": "TR"}],
        last_alert=datetime(2026, 6, 3, 8, 0, tzinfo=UTC),
    )
    message = _FakeMessage(_FakeUser(123, "Іван", "ivan"))

    await profile_mod.show_profile(message)  # type: ignore[arg-type]

    body = message.answers[0]["text"]
    assert "Останній алерт:" in body


@pytest.mark.asyncio
async def test_show_profile_no_user_is_noop(monkeypatch) -> None:
    _patch_db(monkeypatch, subs=[], last_alert=None)
    message = _FakeMessage(None)

    await profile_mod.show_profile(message)  # type: ignore[arg-type]

    assert message.answers == []


def test_settings_alias_registered_in_commands_router() -> None:
    """/settings is registered exactly once, in the commands router, and
    routes to the same account hub as /profile (cmd_settings → show_profile).
    We assert the handler exists rather than driving aiogram's dispatcher."""
    assert hasattr(commands_mod, "cmd_settings")
