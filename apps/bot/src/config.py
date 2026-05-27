"""Bot configuration — inherits shared base, adds Telegram + alert-webhook bits.

TELEGRAM_BOT_TOKEN absence is first-class: the bot logs and idles so an
unconfigured dev environment keeps docker-compose green.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from shared.infra.base_settings import BaseAppSettings


class Settings(BaseAppSettings):
    # Bot uses logical Redis DB /2 so FSM state doesn't collide with the
    # scheduler's refresh:queue list on DB /0.
    redis_url: str = "redis://redis:6379/2"

    # Bot identity.
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None
    telegram_alerts_chat_id: str | None = None
    public_channel_link: str = "https://t.me/fasttravel_deals"

    # Backend HTTP API. In docker-compose this resolves to the api service;
    # for local pytest runs we fall back to the published port on host.
    api_base_url: str = "http://api:8000"

    # Direct DB access for subscriber filters (bot is canonical writer).
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )

    metrics_port: int = 9102

    # Sprint 2.3 — Prometheus AlertManager webhook listener. Port chosen
    # next-after metrics_port; both internal-only in docker-compose.
    alert_webhook_port: int = 9103
    alertmanager_webhook_secret: str | None = None

    # Public Next.js site URL used in deep links / CTA buttons.
    # Intentionally no default: fasttravel.com.ua may point at an
    # unrelated PHP storefront until DNS/Cloudflare frontend deploy is done.
    public_site_url: str | None = None

    @property
    def has_public_site(self) -> bool:
        return bool(self.public_site_url)

    def _extra_prod_offenders(self) -> list[str]:
        offenders: list[str] = []
        if not self.telegram_bot_token:
            offenders.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_channel_id:
            offenders.append("TELEGRAM_CHANNEL_ID")
        if not self.telegram_alerts_chat_id:
            offenders.append("TELEGRAM_ALERTS_CHAT_ID")
        if (
            self.telegram_alerts_chat_id
            and self.telegram_channel_id
            and self.telegram_alerts_chat_id == self.telegram_channel_id
        ):
            offenders.append("TELEGRAM_ALERTS_CHAT_ID_MUST_DIFFER_FROM_TELEGRAM_CHANNEL_ID")
        # Audit #2 — without this secret the /alerts webhook would silently
        # accept any spoofed AlertManager payload from anyone with network
        # reach. Required in prod; the alert_webhook handler also fail-closes
        # at request time so a misconfigured deploy can't slip past.
        if not self.alertmanager_webhook_secret:
            offenders.append("ALERTMANAGER_WEBHOOK_SECRET")
        return offenders


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
