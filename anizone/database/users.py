"""`users` jadvali: foydalanuvchi profili, sozlamalari, ban va ommaviy xabar uchun ro'yxat."""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import asyncpg

from config import MENU_INLINE, MENU_REPLY, SUPPORTED_LANGS
from database.connection import db, rows_affected

Record = asyncpg.Record

NICKNAME_MAX_LENGTH = 32


# ---------------------------------------------------------------------------
# Yaratish va o'qish
# ---------------------------------------------------------------------------
async def upsert_user(user_id: int, username: str | None, first_name: str) -> tuple[Record, bool]:
    """Foydalanuvchini yaratadi yoki yangilaydi.

    Qaytaradi: (foydalanuvchi qatori, yangi_mi). Foydalanuvchi botni qayta ishga
    tushirsa, `is_blocked` belgisi olib tashlanadi.
    """
    row = await db.fetchrow(
        """
        INSERT INTO users (user_id, username, first_name, nickname)
        VALUES ($1, $2, $3, LEFT($3, $4))
        ON CONFLICT (user_id) DO UPDATE
           SET username    = EXCLUDED.username,
               first_name  = EXCLUDED.first_name,
               is_blocked  = FALSE,
               last_active = now()
        RETURNING *, (xmax = 0) AS is_new
        """,
        user_id, username, first_name, NICKNAME_MAX_LENGTH,
    )
    assert row is not None
    return row, bool(row["is_new"])


async def get_user(user_id: int) -> Record | None:
    return await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def find_user(query: str) -> Record | None:
    """ID (raqam) yoki @username bo'yicha topadi. Owner panelda VIP berish uchun."""
    query = query.strip()
    if query.lstrip("-").isdigit():
        return await get_user(int(query))
    username = query.lstrip("@").strip()
    if not username:
        return None
    return await db.fetchrow(
        "SELECT * FROM users WHERE lower(username) = lower($1)", username
    )


async def get_lang(user_id: int) -> str | None:
    """Tanlangan til; hali tanlanmagan bo'lsa None."""
    return await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user_id)


async def touch_last_active(user_id: int) -> None:
    await db.execute("UPDATE users SET last_active = now() WHERE user_id = $1", user_id)


# ---------------------------------------------------------------------------
# Sozlamalar
# ---------------------------------------------------------------------------
async def set_lang(user_id: int, lang: str) -> None:
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Noma'lum til: {lang!r}")
    await db.execute("UPDATE users SET lang = $2 WHERE user_id = $1", user_id, lang)


async def set_menu_type(user_id: int, menu_type: str) -> None:
    if menu_type not in (MENU_REPLY, MENU_INLINE):
        raise ValueError(f"Noma'lum menyu turi: {menu_type!r}")
    await db.execute("UPDATE users SET menu_type = $2 WHERE user_id = $1", user_id, menu_type)


async def toggle_menu_type(user_id: int) -> str | None:
    """Pastki menyu <-> inline menyu. Yangi qiymatni qaytaradi."""
    return await db.fetchval(
        """
        UPDATE users
           SET menu_type = CASE menu_type WHEN 'reply' THEN 'inline' ELSE 'reply' END
         WHERE user_id = $1
        RETURNING menu_type
        """,
        user_id,
    )


async def set_nickname(user_id: int, nickname: str) -> None:
    """Nikni saqlaydi. Matnni tekshirish (uzunlik, belgilar) chaqiruvchi tomonda qilinadi."""
    await db.execute(
        "UPDATE users SET nickname = LEFT($2, $3) WHERE user_id = $1",
        user_id, nickname, NICKNAME_MAX_LENGTH,
    )


async def toggle_ai_memory(user_id: int) -> bool | None:
    """AI xotirasini yoqadi/o'chiradi. Yangi qiymatni qaytaradi."""
    return await db.fetchval(
        "UPDATE users SET ai_memory = NOT ai_memory WHERE user_id = $1 RETURNING ai_memory",
        user_id,
    )


# ---------------------------------------------------------------------------
# Ban va bloklash
# ---------------------------------------------------------------------------
async def ban_user(user_id: int, reason: str | None = None) -> bool:
    status = await db.execute(
        "UPDATE users SET is_banned = TRUE, ban_reason = $2 WHERE user_id = $1",
        user_id, reason,
    )
    return rows_affected(status) > 0


async def unban_user(user_id: int) -> bool:
    status = await db.execute(
        "UPDATE users SET is_banned = FALSE, ban_reason = NULL WHERE user_id = $1",
        user_id,
    )
    return rows_affected(status) > 0


async def is_banned(user_id: int) -> bool:
    return bool(await db.fetchval("SELECT is_banned FROM users WHERE user_id = $1", user_id))


async def set_blocked(user_id: int, blocked: bool) -> None:
    """Foydalanuvchi botni bloklagan bo'lsa True. Ommaviy xabarda o'tkazib yuboriladi."""
    await db.execute("UPDATE users SET is_blocked = $2 WHERE user_id = $1", user_id, blocked)


# ---------------------------------------------------------------------------
# Ommaviy xabar va statistika
# ---------------------------------------------------------------------------
async def iter_broadcast_ids(batch_size: int = 1000) -> AsyncIterator[int]:
    """Xabar yuboriladigan foydalanuvchilar ID si (ban va bloklanganlarsiz).

    Hammasini xotiraga yuklamaydi: ID bo'yicha bo'laklab o'qiydi.
    """
    last_id = 0
    while True:
        rows = await db.fetch(
            """
            SELECT user_id FROM users
             WHERE user_id > $1 AND is_banned = FALSE AND is_blocked = FALSE
             ORDER BY user_id
             LIMIT $2
            """,
            last_id, batch_size,
        )
        if not rows:
            return
        for row in rows:
            yield row["user_id"]
        last_id = rows[-1]["user_id"]


async def count_users() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users")


async def count_banned() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE is_banned")


async def count_blocked() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked")


async def count_joined_since(since: datetime) -> int:
    """`since` dan keyin qo'shilgan foydalanuvchilar (masalan, bugungi yangilar)."""
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE joined_at >= $1", since)
