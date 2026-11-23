"""`episodes` jadvali: qismlar (videolar file_id sifatida saqlanadi).

Qism raqami (`number`) anime ichida takrorlanmaydi. Qism o'chirilsa, qolganlarning
raqami o'zgarmaydi (36 dan keyin 38 qoladi), keyin 37 qo'shilsa o'z joyiga tushadi.
Anime nomi va kodi `animes` jadvalidan JOIN orqali olinadi.
"""
from __future__ import annotations

import asyncpg

from database.connection import db, rows_affected

Record = asyncpg.Record

# Ketma-ket qism qo'shishda bir anime uchun navbat (pg_advisory_xact_lock ning birinchi kaliti)
_EPISODE_LOCK_NS = 7_002


# ---------------------------------------------------------------------------
# Qo'shish
# ---------------------------------------------------------------------------
async def add_episode(
    anime_id: int,
    number: int,
    file_id: str,
    file_unique_id: str | None,
    is_vip: bool,
) -> bool:
    """Aniq raqam bilan qo'shadi. Bu raqam band bo'lsa, False qaytaradi."""
    new_id = await db.fetchval(
        """
        INSERT INTO episodes (anime_id, number, file_id, file_unique_id, is_vip)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (anime_id, number) DO NOTHING
        RETURNING id
        """,
        anime_id, number, file_id, file_unique_id, is_vip,
    )
    return new_id is not None


async def add_next_episode(
    anime_id: int,
    file_id: str,
    file_unique_id: str | None,
    is_vip: bool,
) -> int:
    """Ketma-ket rejim: eng katta raqamdan keyingisini beradi. Qo'yilgan raqamni qaytaradi."""
    async with db.transaction() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1, $2)", _EPISODE_LOCK_NS, anime_id)
        number = await conn.fetchval(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM episodes WHERE anime_id = $1", anime_id
        )
        await conn.execute(
            """
            INSERT INTO episodes (anime_id, number, file_id, file_unique_id, is_vip)
            VALUES ($1, $2, $3, $4, $5)
            """,
            anime_id, number, file_id, file_unique_id, is_vip,
        )
    return number


async def replace_episode(
    anime_id: int,
    number: int,
    file_id: str,
    file_unique_id: str | None,
    is_vip: bool,
) -> None:
    """Mavjud qism videosini almashtiradi (yo'q bo'lsa, yangisini yaratadi)."""
    await db.execute(
        """
        INSERT INTO episodes (anime_id, number, file_id, file_unique_id, is_vip)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (anime_id, number) DO UPDATE
           SET file_id = EXCLUDED.file_id,
               file_unique_id = EXCLUDED.file_unique_id,
               is_vip = EXCLUDED.is_vip
        """,
        anime_id, number, file_id, file_unique_id, is_vip,
    )


# ---------------------------------------------------------------------------
# O'qish
# ---------------------------------------------------------------------------
async def get_episode(anime_id: int, number: int) -> Record | None:
    """Qism + anime nomi, kodi va anime VIP belgisi (tomosha qilish uchun kerak bo'ladigan hammasi)."""
    return await db.fetchrow(
        """
        SELECT e.*, a.title AS anime_title, a.is_vip AS anime_is_vip
          FROM episodes e
          JOIN animes a ON a.id = e.anime_id
         WHERE e.anime_id = $1 AND e.number = $2
        """,
        anime_id, number,
    )


async def list_numbers(anime_id: int) -> list[Record]:
    """Anime qismlarining raqamlari va VIP belgisi, o'sish tartibida (tugmalar uchun)."""
    return await db.fetch(
        "SELECT number, is_vip FROM episodes WHERE anime_id = $1 ORDER BY number",
        anime_id,
    )


async def count_episodes(anime_id: int) -> int:
    return await db.fetchval("SELECT COUNT(*) FROM episodes WHERE anime_id = $1", anime_id)


async def count_all() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM episodes")


async def max_number(anime_id: int) -> int:
    """Eng katta qism raqami; qism yo'q bo'lsa 0."""
    return await db.fetchval(
        "SELECT COALESCE(MAX(number), 0) FROM episodes WHERE anime_id = $1", anime_id
    )


async def get_neighbors(anime_id: int, number: int) -> tuple[int | None, int | None]:
    """Oldingi va keyingi MAVJUD qism raqami (oradagi o'chirilgan raqamlar o'tkazib yuboriladi)."""
    row = await db.fetchrow(
        """
        SELECT (SELECT MAX(number) FROM episodes WHERE anime_id = $1 AND number < $2) AS prev,
               (SELECT MIN(number) FROM episodes WHERE anime_id = $1 AND number > $2) AS next
        """,
        anime_id, number,
    )
    if row is None:
        return None, None
    return row["prev"], row["next"]


# ---------------------------------------------------------------------------
# Tahrirlash va o'chirish
# ---------------------------------------------------------------------------
async def set_episode_vip(anime_id: int, number: int, is_vip: bool) -> bool:
    status = await db.execute(
        "UPDATE episodes SET is_vip = $3 WHERE anime_id = $1 AND number = $2",
        anime_id, number, is_vip,
    )
    return rows_affected(status) > 0


async def delete_episode(anime_id: int, number: int) -> bool:
    """Faqat shu qismni o'chiradi; qolganlarning raqami o'zgarmaydi."""
    status = await db.execute(
        "DELETE FROM episodes WHERE anime_id = $1 AND number = $2", anime_id, number
    )
    return rows_affected(status) > 0
