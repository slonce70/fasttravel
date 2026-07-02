"""Discovery handler — logs chat_id of channels/groups the bot is added to.

Why this exists: a private Telegram channel doesn't expose its numeric
chat_id in any user-visible place. The owner adds the bot as admin via
the invite link, Telegram fires a `my_chat_member` update, and we
structured-log the chat info so the operator can grab the id from
docker logs and stick it in TELEGRAM_CHANNEL_ID.

Idempotent: it just logs. Safe to keep in the dispatcher long-term as
useful diagnostic if the operator ever needs to discover a chat_id again.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from src.infra.logging import get_logger

router = Router(name="admin_discovery")
log = get_logger(__name__)


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """Fires whenever the bot's membership changes in any chat — added,
    promoted to admin, demoted, removed. We log the chat coordinates
    every time so the operator can find the numeric chat_id."""
    chat = event.chat
    old_status = event.old_chat_member.status if event.old_chat_member else None
    new_status = event.new_chat_member.status if event.new_chat_member else None
    log.info(
        "bot.discovery.membership_changed",
        chat_id=chat.id,
        chat_type=chat.type,
        chat_title=chat.title,
        chat_username=getattr(chat, "username", None),
        old_status=old_status,
        new_status=new_status,
        promoted_by=event.from_user.id if event.from_user else None,
        hint=("Set TELEGRAM_CHANNEL_ID to this chat_id in .env if this is the broadcast channel."),
    )
