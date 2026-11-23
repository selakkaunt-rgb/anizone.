"""`ai_history` jadvali: AI suhbat tarixi. Faqat foydalanuvchida "AI Xotira: Yoniq" bo'lsa yoziladi."""
from __future__ import annotations

import asyncpg

from database.connection import db

Record = asyncpg.Record

_MAX_CONTENT_LENGTH = 8000
_ROLES = ("user", "assistant")


async def add_message(user_id: int, role: str, content: str) -> None:
    if role not in _ROLES:
        raise ValueError(f"Noma'lum rol: {role!r}")
    await db.execute(
        "INSERT INTO ai_history (user_id, role, content) VALUES ($1, $2, $3)",
        user_id, role, content[:_MAX_CONTENT_LENGTH],
    )


async def get_recent(user_id: int, limit: int = 10) -> list[Record]:
    """Oxirgi `limit` ta xabar, eskisidan yangisiga qarab (AI ga shu tartibda beriladi)."""
    return await db.fetch(
        """
        SELECT role, content FROM (
            SELECT id, role, content FROM ai_history
             WHERE user_id = $1
             ORDER BY id DESC
             LIMIT $2
        ) AS recent
        ORDER BY id
        """,
        user_id, limit,
    )


async def trim(user_id: int, keep: int = 50) -> None:
    """Eng yangi `keep` ta xabardan boshqasini o'chiradi (baza hajmini nazorat qilish uchun)."""
    await db.execute(
        """
        DELETE FROM ai_history
         WHERE user_id = $1
           AND id NOT IN (
               SELECT id FROM ai_history WHERE user_id = $1 ORDER BY id DESC LIMIT $2
           )
        """,
        user_id, keep,
    )


async def clear(user_id: int) -> None:
    await db.execute("DELETE FROM ai_history WHERE user_id = $1", user_id)
