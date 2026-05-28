from __future__ import annotations

import importlib
import re
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def test_current_prices_room_family_is_materialized_and_indexed(monkeypatch) -> None:
    migration = importlib.import_module("migrations.versions.021_current_prices_room_family")
    statements: list[str] = []

    monkeypatch.setattr(migration, "op", SimpleNamespace(execute=statements.append))

    migration.upgrade()

    sql = "\n".join(statements)
    assert "AS room_family" in sql
    assert "trim(regexp_replace(lower(coalesce(room_category, ''))" in sql
    assert "LIKE '% deluxe %'" in sql
    assert "LIKE '% superior %'" in sql
    assert "LIKE '% bungalow %'" in sql
    assert "LIKE '% ssv %'" in sql
    assert "LIKE '% inland view %'" in sql
    assert "LIKE '% roh %'" in sql
    assert "LIKE '% standart %'" in sql
    assert "LIKE '% br %'" in sql
    assert (
        "ON current_prices (hotel_id, operator_id, nights, meal_plan, room_family, check_in)" in sql
    )
    assert "INCLUDE (price_uah, deep_link, room_category)" in sql


def _room_family_for(label: str) -> str:
    migration = importlib.import_module("migrations.versions.021_current_prices_room_family")
    room_norm = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    padded = f" {room_norm} "

    if " studio " in padded:
        base = "studio"
    elif " junior suite " in padded or " suite " in padded:
        base = "suite"
    elif " bungalow " in padded:
        base = "bungalow"
    elif " villa " in padded:
        base = "villa"
    elif any(f" {token} " in padded for token in migration._APARTMENT_ROOM_TOKENS):
        base = "apartment"
    elif " family " in padded:
        base = "family"
    elif any(f" {token} " in padded for token in migration._DELUXE_ROOM_TOKENS):
        base = "deluxe"
    elif any(f" {token} " in padded for token in migration._SUPERIOR_ROOM_TOKENS):
        base = "superior"
    elif any(f" {token} " in padded for token in migration._PREMIUM_ROOM_TOKENS):
        base = "premium"
    elif any(f" {token} " in padded for token in migration._COMFORT_ROOM_TOKENS):
        base = "comfort"
    elif any(f" {token} " in padded for token in migration._ECONOMY_ROOM_TOKENS):
        base = "economy"
    elif any(f" {token} " in padded for token in migration._STANDARD_ROOM_TOKENS):
        base = "standard"
    else:
        base = "other"

    if any(f" {token} " in padded for token in migration._SEA_VIEW_TOKENS):
        view = "sea"
    elif any(f" {token} " in padded for token in migration._LAND_VIEW_TOKENS):
        view = "land"
    elif any(f" {token} " in padded for token in migration._GARDEN_VIEW_TOKENS):
        view = "garden"
    elif any(f" {token} " in padded for token in migration._POOL_VIEW_TOKENS):
        view = "pool"
    else:
        view = "any"

    return f"{base}:{view}"


def test_room_family_covers_frequent_farvater_room_aliases() -> None:
    assert _room_family_for("DELUXE") == "deluxe:any"
    assert _room_family_for("SUPERIOR") == "superior:any"
    assert _room_family_for("ECONOMY") == "economy:any"
    assert _room_family_for("TWIN INLAND VIEW") == "standard:land"
    assert _room_family_for("BUNGALOW GARDEN VIEW") == "bungalow:garden"
    assert _room_family_for("DELUXE SSV") == "deluxe:sea"
    assert _room_family_for("PREMIUM GV") == "premium:garden"
    assert _room_family_for("Comfort") == "comfort:any"
    assert _room_family_for("ROH") == "standard:any"
    assert _room_family_for("STANDART 1/2") == "standard:any"
    assert _room_family_for("STD SEA SIDE VIEW") == "standard:sea"
    assert _room_family_for("1-BR. CV") == "apartment:any"
    assert _room_family_for("ONE BEDROOM") == "apartment:any"


@pytest.mark.asyncio
async def test_current_prices_materializes_room_family_for_real_alias_rows(
    db_session: AsyncSession,
) -> None:
    operator_id = await db_session.scalar(
        text(
            """
            INSERT INTO operators (code, display_name)
            VALUES ('room-family-aliases', 'Room Family Aliases')
            RETURNING id
            """
        )
    )
    hotel_id = await db_session.scalar(
        text(
            """
            INSERT INTO hotels (canonical_slug, name_uk, is_active)
            VALUES ('room-family-aliases-hotel', 'Room Family Aliases Hotel', TRUE)
            RETURNING id
            """
        )
    )
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))
    assert isinstance(operator_id, int)
    assert isinstance(hotel_id, int)
    assert isinstance(db_today, date)
    assert db_now is not None

    await db_session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                :observed_at, :hotel_id, :operator_id, :check_in, 7, 'AI',
                :room_category, :price_uah, 'UAH', :deep_link
            )
            """
        ),
        [
            {
                "observed_at": db_now,
                "hotel_id": hotel_id,
                "operator_id": operator_id,
                "check_in": db_today,
                "room_category": room_category,
                "price_uah": 100000 + idx,
                "deep_link": f"https://example.test/room-family/{idx}",
            }
            for idx, room_category in enumerate(
                [
                    "DELUXE",
                    "SUPERIOR",
                    "ECONOMY",
                    "Comfort",
                    "TWIN INLAND VIEW",
                    "BUNGALOW GARDEN VIEW",
                    "DELUXE SSV",
                    "PREMIUM GV",
                    "ROH",
                    "STANDART 1/2",
                    "STD SEA SIDE VIEW",
                    "1-BR. CV",
                    "ONE BEDROOM",
                ]
            )
        ],
    )
    await db_session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))

    rows = (
        await db_session.execute(
            text(
                """
                SELECT room_category, room_family
                FROM current_prices
                WHERE hotel_id = :hotel_id
                  AND operator_id = :operator_id
                ORDER BY room_category
                """
            ),
            {"hotel_id": hotel_id, "operator_id": operator_id},
        )
    ).mappings()

    actual = {row["room_category"]: row["room_family"] for row in rows}
    assert actual == {
        "1-BR. CV": "apartment:any",
        "BUNGALOW GARDEN VIEW": "bungalow:garden",
        "Comfort": "comfort:any",
        "DELUXE": "deluxe:any",
        "DELUXE SSV": "deluxe:sea",
        "ECONOMY": "economy:any",
        "ONE BEDROOM": "apartment:any",
        "PREMIUM GV": "premium:garden",
        "ROH": "standard:any",
        "STANDART 1/2": "standard:any",
        "STD SEA SIDE VIEW": "standard:sea",
        "SUPERIOR": "superior:any",
        "TWIN INLAND VIEW": "standard:land",
    }
