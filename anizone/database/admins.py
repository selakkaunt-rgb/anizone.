"""`admins` jadvali. Owner bu yerda turmaydi: u `OWNER_ID` muhit o'zgaruvchisidan olinadi.

Huquq tekshiruvi har so'rovda bazadan o'qiladi (kesh yo'q), shuning uchun admin
olib tashlansa, darhol kuchga kiradi.
"""
from __future__ import annotations

import asyncpg

from database.connection import db, rows_affected

Record = asyncpg.Record


async def add_admin(user_id: int, added_by: int | None) -> bool:
    """Admin qo'shadi. U allaqachon admin bo'lsa, False qaytaradi."""
    new_id = await db.fetchval(
        """
        INSERT INTO admins (user_id, added_by) VALUES ($1, $2)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING user_id
        """,
        user_id, added_by,
    )
    return new_id is not None


async def remove_admin(user_id: int) -> bool:
    status = await db.execute("DELETE FROM admins WHERE user_id = $1", user_id)
    return rows_affected(status) > 0


async def is_admin(user_id: int) -> bool:
    return bool(
        await db.fetchval("SELECT EXISTS (SELECT 1 FROM admins WHERE user_id = $1)", user_id)
    )


async def list_admins() -> list[Record]:
    """Adminlar ro'yxati (username va ismi bilan, agar foydalanuvchi botga kirgan bo'lsa)."""
    return await db.fetch(
        """
        SELECT a.user_id, a.added_by, a.added_at, u.username, u.first_name
          FROM admins a
          LEFT JOIN users u ON u.user_id = a.user_id
         ORDER BY a.added_at
        """
    )
