"""`settings` jadvali: owner paneldan o'zgartiriladigan qiymatlar (karta, narxlar, havolalar)."""
from __future__ import annotations

from config import DEFAULT_SETTINGS, PLANS, price_setting_key
from database.connection import db
from utils.logger import get_logger

log = get_logger(__name__)


async def ensure_defaults() -> None:
    """Yetishmayotgan sozlamalarni boshlang'ich qiymat bilan yaratadi. Mavjudlarini o'zgartirmaydi."""
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
            key, value,
        )


async def get_setting(key: str, default: str = "") -> str:
    value = await db.fetchval("SELECT value FROM settings WHERE key = $1", key)
    return default if value is None else value


async def set_setting(key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, value,
    )


# ---------------------------------------------------------------------------
# VIP narxlari
# ---------------------------------------------------------------------------
async def get_prices() -> dict[str, int]:
    """Hamma tarif narxlari: {'3_month': 50000, ...}. Qiymat buzilgan bo'lsa, boshlang'ich narx olinadi."""
    keys = [price_setting_key(key) for key in PLANS]
    rows = await db.fetch("SELECT key, value FROM settings WHERE key = ANY($1::text[])", keys)
    stored = {row["key"]: row["value"] for row in rows}

    prices: dict[str, int] = {}
    for plan in PLANS.values():
        raw = stored.get(price_setting_key(plan.key))
        try:
            amount = int(raw) if raw is not None else plan.default_price
        except ValueError:
            amount = plan.default_price
        if amount <= 0:
            amount = plan.default_price
        prices[plan.key] = amount
    return prices


async def get_price(plan_key: str) -> int:
    if plan_key not in PLANS:
        raise ValueError(f"Noma'lum tarif: {plan_key!r}")
    return (await get_prices())[plan_key]


async def set_price(plan_key: str, amount: int) -> None:
    if plan_key not in PLANS:
        raise ValueError(f"Noma'lum tarif: {plan_key!r}")
    if amount <= 0:
        raise ValueError("Narx musbat bo'lishi kerak.")
    await set_setting(price_setting_key(plan_key), str(amount))
