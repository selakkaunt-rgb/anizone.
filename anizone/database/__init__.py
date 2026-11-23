"""
Baza qatlami.

Ishlatilishi:
    from database.connection import db
    from database import animes, episodes, users, vip   # yoki kerakli modul

Dastur boshida `await init_database()` chaqiriladi.
"""
from __future__ import annotations


async def init_database() -> None:
    """Bazaga ulanadi, jadvallarni yaratadi/yangilaydi va boshlang'ich sozlamalarni qo'yadi."""
    # Aylanma import bo'lmasligi uchun funksiya ichida
    from database.connection import db
    from database.schema import run_migrations
    from database.settings import ensure_defaults

    await db.connect()
    await run_migrations()
    await ensure_defaults()
