from __future__ import annotations

import importlib
from datetime import date
from types import SimpleNamespace

import pytest

module = importlib.import_module("src.jobs.post_cheapest_digest")
post_cheapest_digest = module.post_cheapest_digest
render_digest = module.render_digest


def _settings(**overrides):
    values = {
        "telegram_enabled": True,
        "telegram_bot_token": "token",
        "telegram_channel_id": "-100123",
        "public_site_url": "https://fasttravel.test",
        "telegram_send_delay_seconds": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(
    *,
    country_iso2: str,
    country_name: str | None,
    hotel_id: int,
    hotel_name: str,
    price_uah: int,
    rank: int,
    deep_link: str | None = "https://farvater.travel/hotel/x",
    hotel_slug: str = "fv-x",
    stars: int = 3,
    meal_plan: str = "RO",
) -> SimpleNamespace:
    return SimpleNamespace(
        country_iso2=country_iso2,
        country_name=country_name,
        hotel_id=hotel_id,
        hotel_slug=hotel_slug,
        hotel_name=hotel_name,
        stars=stars,
        review_score=8.5,
        review_count=4,
        check_in=date(2026, 6, 6),
        nights=7,
        meal_plan=meal_plan,
        price_uah=price_uah,
        deep_link=deep_link,
        rank=rank,
    )


# Two countries, three hotels each — back-to-back, ordered like the shared SQL
# returns (country_name, rank, hotel_id).
def _two_country_rows() -> list[SimpleNamespace]:
    return [
        _row(country_iso2="BG", country_name="Болгарія", hotel_id=1,
             hotel_name="Chuchulev Hotel", price_uah=18210, rank=1),
        _row(country_iso2="BG", country_name="Болгарія", hotel_id=2,
             hotel_name="Topalovi Family Hotel", price_uah=18868, rank=2),
        _row(country_iso2="BG", country_name="Болгарія", hotel_id=3,
             hotel_name="Ryor Hotel", price_uah=18949, rank=3),
        _row(country_iso2="TR", country_name="Туреччина", hotel_id=4,
             hotel_name="Sea Hotel", price_uah=25000, rank=1, meal_plan="AI"),
        _row(country_iso2="TR", country_name="Туреччина", hotel_id=5,
             hotel_name="Sun Resort", price_uah=26000, rank=2, meal_plan="AI"),
        _row(country_iso2="TR", country_name="Туреччина", hotel_id=6,
             hotel_name="Bay Hotel", price_uah=27000, rank=3, meal_plan="AI"),
    ]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql, params=None):
        return _Result(self._rows)


class _FakeBot:
    def __init__(self):
        self.session = SimpleNamespace(closed=False)

        async def close():
            self.session.closed = True

        self.session.close = close


# --------------------------------------------------------------------------- #
# render_digest — pure formatting
# --------------------------------------------------------------------------- #


# Eleven countries with long names + slugs — the real prod scale. Used to prove
# the digest chunks rather than overflowing Telegram's 4096-char message limit.
_COUNTRIES_11 = [
    "Болгарія", "Туреччина", "Єгипет", "Чорногорія", "Кіпр", "Греція",
    "Іспанія", "Туніс", "Об'єднані Арабські Емірати",
    "Домініканська Республіка", "Танзанія",
]


def _eleven_country_rows() -> list[SimpleNamespace]:
    rows = []
    hid = 0
    for c in _COUNTRIES_11:
        for r in range(1, 4):
            hid += 1
            rows.append(
                SimpleNamespace(
                    country_iso2=c[:2],
                    country_name=c,
                    hotel_id=hid,
                    hotel_slug=f"fv-some-very-long-hotel-slug-{hid}",
                    hotel_name=f"Grand Palace Resort & Spa Deluxe {hid}",
                    stars=5,
                    review_score=9.0,
                    review_count=10,
                    check_in=date(2026, 6, 28),
                    nights=14,
                    meal_plan="Ультра все включено",
                    price_uah=199999,
                    deep_link=None,
                    rank=r,
                )
            )
    return rows


def test_render_digest_groups_by_country_with_honest_price_copy():
    chunks = render_digest(_two_country_rows(), public_site_url="https://fasttravel.test")
    # Two countries fit one message.
    assert len(chunks) == 1
    text = chunks[0]

    # Title + both country headers present.
    assert "Найдешевші тури по напрямках" in text
    assert "Болгарія" in text
    assert "Туреччина" in text

    # Every hotel renders.
    for name in ("Chuchulev Hotel", "Ryor Hotel", "Sea Hotel", "Bay Hotel"):
        assert name in text

    # Honest «ціна від» copy — and NEVER a discount framing.
    assert "ціна від" in text
    assert "знижка" not in text
    assert "%" not in text
    # The MarkdownV2 minus is escaped as "\-"; a discount would show a bare
    # "−"/"-X%". Neither the unicode minus sign nor a "-NN" run appears.
    assert "−" not in text
    import re

    assert re.search(r"-\d", text) is None


def test_render_digest_links_are_deep_links_with_fallback_to_hotel_page():
    rows = [
        _row(country_iso2="BG", country_name="Болгарія", hotel_id=1,
             hotel_name="With Link", price_uah=18210, rank=1,
             deep_link="https://farvater.travel/hotel/bg/x"),
        _row(country_iso2="BG", country_name="Болгарія", hotel_id=2,
             hotel_name="No Link", price_uah=18868, rank=2,
             deep_link=None, hotel_slug="fv-bg-y"),
    ]
    chunks = render_digest(rows, public_site_url="https://fasttravel.test")
    text = "\n\n".join(chunks)

    assert "https://farvater.travel/hotel/bg/x" in text
    # Fallback to the public hotel page when no operator deep link.
    assert "https://fasttravel.test/hotels/fv-bg-y" in text


def test_render_digest_chunks_at_scale_without_overflow_or_splitting_country():
    from src.jobs.post_cheapest_digest import _CHUNK_CHAR_BUDGET

    chunks = render_digest(_eleven_country_rows(), public_site_url="https://fasttravel.com.ua")

    # 11 countries × 3 hotels with deep links cannot fit one 4096-char message.
    assert len(chunks) >= 2
    # Title appears in exactly one chunk (the first only).
    assert sum("Найдешевші тури по напрямках" in c for c in chunks) == 1
    # Every chunk stays under budget (and thus under Telegram's hard 4096).
    for c in chunks:
        assert len(c) <= _CHUNK_CHAR_BUDGET
    # No country header split across a boundary: each country header appears in
    # exactly one chunk (a country block is atomic, so its 3 hotel lines stay
    # with it). Match the escaped name as rendered (e.g. apostrophes escaped).
    from src.jobs.post_cheapest_digest import escape_markdown_v2

    for c in _COUNTRIES_11:
        header = f"🌍 *{escape_markdown_v2(c)}*"
        assert sum(header in chunk for chunk in chunks) == 1, c


# --------------------------------------------------------------------------- #
# post_cheapest_digest — orchestration / gating
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_skipped_when_flag_disabled_does_not_touch_db_or_bot(monkeypatch):
    monkeypatch.delenv(module.FEATURE_FLAG_ENV, raising=False)
    monkeypatch.setattr(
        module,
        "async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("db should not be touched")),
    )
    monkeypatch.setattr(
        module,
        "make_bot",
        lambda _t: (_ for _ in ()).throw(AssertionError("bot should not be created")),
    )
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("settings should not be read")),
    )

    await post_cheapest_digest()


@pytest.mark.asyncio
async def test_skipped_when_telegram_token_missing(monkeypatch):
    monkeypatch.setenv(module.FEATURE_FLAG_ENV, "1")
    monkeypatch.setattr(module, "get_settings", lambda: _settings(telegram_enabled=False))
    monkeypatch.setattr(
        module,
        "async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("db should not be touched")),
    )
    monkeypatch.setattr(
        module,
        "make_bot",
        lambda _t: (_ for _ in ()).throw(AssertionError("bot should not be created")),
    )

    await post_cheapest_digest()


@pytest.mark.asyncio
async def test_no_rows_does_not_send(monkeypatch):
    monkeypatch.setenv(module.FEATURE_FLAG_ENV, "1")
    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession([]))
    monkeypatch.setattr(
        module,
        "make_bot",
        lambda _t: (_ for _ in ()).throw(AssertionError("bot should not be created")),
    )

    await post_cheapest_digest()


@pytest.mark.asyncio
async def test_sends_single_digest_when_enabled(monkeypatch):
    monkeypatch.setenv(module.FEATURE_FLAG_ENV, "1")
    bot = _FakeBot()
    sent: list[tuple] = []

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession(_two_country_rows()))
    monkeypatch.setattr(module, "make_bot", lambda _t: bot)

    async def broadcast(_bot, channel, text, *, disable_web_page_preview=False):
        sent.append((channel, text, disable_web_page_preview))
        return 555

    monkeypatch.setattr(module, "broadcast_deal", broadcast)

    await post_cheapest_digest()

    # Two countries fit in ONE message — small inputs are not gratuitously split.
    assert len(sent) == 1
    channel, text, no_preview = sent[0]
    assert channel == -100123  # coerced to int
    assert no_preview is True
    assert "Найдешевші тури по напрямках" in text
    assert "Болгарія" in text and "Туреччина" in text
    assert "ціна від" in text
    assert "знижка" not in text and "%" not in text
    # Bot session closed even on the happy path.
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_sends_multiple_chunks_at_prod_scale(monkeypatch):
    monkeypatch.setenv(module.FEATURE_FLAG_ENV, "1")
    bot = _FakeBot()
    sent: list[tuple] = []

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        module, "async_session_factory", lambda: _FakeSession(_eleven_country_rows())
    )
    monkeypatch.setattr(module, "make_bot", lambda _t: bot)

    async def broadcast(_bot, channel, text, *, disable_web_page_preview=False):
        sent.append((channel, text, disable_web_page_preview))
        return 1000 + len(sent)

    monkeypatch.setattr(module, "broadcast_deal", broadcast)

    await post_cheapest_digest()

    # 11×3 with deep links cannot fit one message → the daily digest is
    # transport-chunked into >=2 messages. Title in exactly one.
    assert len(sent) >= 2
    assert sum("Найдешевші тури по напрямках" in t for _c, t, _p in sent) == 1
    assert all(no_preview is True for _c, _t, no_preview in sent)
    assert all(len(t) <= module._CHUNK_CHAR_BUDGET for _c, t, _p in sent)
    assert bot.session.closed is True
