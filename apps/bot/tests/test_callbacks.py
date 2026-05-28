from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from aiogram.types import Chat, Message, User

from src.infra import callbacks
from src.infra.callbacks import callback_message


def _make_message(uid: int = 42) -> Message:
    return Message.model_construct(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat.model_construct(id=uid, type="private"),
        from_user=User.model_construct(id=uid, is_bot=False, first_name="Test"),
        text="hi",
    )


def test_callback_message_returns_editable_message() -> None:
    message = _make_message()
    query = SimpleNamespace(message=message)

    assert callback_message(query) is message  # type: ignore[arg-type]


def test_callback_message_drops_inaccessible_payload() -> None:
    query = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=42)))

    assert callback_message(query) is None  # type: ignore[arg-type]


def test_callback_message_drops_missing_payload() -> None:
    query = SimpleNamespace(message=None)

    assert callback_message(query) is None  # type: ignore[arg-type]


def test_callback_tail_extracts_non_empty_suffix() -> None:
    assert callbacks.callback_tail("subb:50000", "subb:") == "50000"
    assert callbacks.callback_tail("subb:", "subb:") is None
    assert callbacks.callback_tail("subs:4", "subb:") is None
    assert callbacks.callback_tail(None, "subb:") is None


def test_callback_int_tail_parses_decimal_suffix_only() -> None:
    assert callbacks.callback_int_tail("subs:4", "subs:") == 4
    assert callbacks.callback_int_tail("subs:any", "subs:") is None
    assert callbacks.callback_int_tail("subs:", "subs:") is None
    assert callbacks.callback_int_tail("subs:4:5", "subs:") is None
