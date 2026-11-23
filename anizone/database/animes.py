"""`animes` jadvali: anime yaratish, tahrirlash, o'chirish va qidirish.

Anime `id` si — uning KODI. VIP va oddiy animelar uchun bitta umumiy ketma-ketlik.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

import asyncpg

from database.connection import db, rows_affected
from utils.helpers import escape_like

Record = asyncpg.Record

# Ketma-ket ID berishda ikki admin bir vaqtda bir xil raqam olmasligi uchun
_ID_LOCK_KEY = 7_001_001

# Tahrirlash mumkin bo'lgan ustunlar. SQL ga ustun nomi qo'yiladigan joyda faqat
# shu ro'yxatdagi nomlar ruxsat etiladi (foydalanuvchi matni hech qachon qo'yilmaydi).
EDITABLE_FIELDS = frozenset({"title", "year", "genres", "studio", "poster_file_id"})

# Ro'yxat tartiblari (kalit: handlerlar ishlatadigan nom)
_ORDERINGS = {
    "top": "views DESC, id ASC",
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "id": "id ASC",
    "title": "lower(title) ASC, id ASC",
}

# trace.moe nomlari bo'yicha "ichida bor" qidiruvi uchun eng qisqa nom uzunligi
# (juda qisqa nom hamma animeni topib yuboradi).
_MIN_FUZZY_LENGTH = 4

_INSERT_SQL = """
    INSERT INTO animes (id, title, year, genres, studio, poster_file_id, is_vip)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


# ---------------------------------------------------------------------------
# Yaratish
# ---------------------------------------------------------------------------
async def id_exists(anime_id: int) -> bool:
    return bool(await db.fetchval("SELECT EXISTS (SELECT 1 FROM animes WHERE id = $1)", anime_id))


async def create_anime(
    anime_id: int,
    title: str,
    year: int | None,
    genres: Sequence[str],
    studio: str | None,
    poster_file_id: str | None,
    is_vip: bool,
) -> bool:
    """O'zi tanlagan ID bilan yaratadi. ID band bo'lsa, False qaytaradi (hech narsa o'zgarmaydi)."""
    new_id = await db.fetchval(
        _INSERT_SQL + " ON CONFLICT (id) DO NOTHING RETURNING id",
        anime_id, title, year, list(genres), studio, poster_file_id, is_vip,
    )
    return new_id is not None


async def create_anime_sequential(
    title: str,
    year: int | None,
    genres: Sequence[str],
    studio: str | None,
    poster_file_id: str | None,
    is_vip: bool,
) -> int:
    """Eng katta ID dan keyingi raqam bilan yaratadi (1, 2, 3...). Berilgan ID ni qaytaradi."""
    async with db.transaction() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _ID_LOCK_KEY)
        new_id = await conn.fetchval("SELECT COALESCE(MAX(id), 0) + 1 FROM animes")
        await conn.execute(
            _INSERT_SQL, new_id, title, year, list(genres), studio, poster_file_id, is_vip
        )
    return new_id


# ---------------------------------------------------------------------------
# O'qish
# ---------------------------------------------------------------------------
async def get_anime(anime_id: int) -> Record | None:
    return await db.fetchrow("SELECT * FROM animes WHERE id = $1", anime_id)


async def get_random() -> Record | None:
    return await db.fetchrow("SELECT * FROM animes ORDER BY random() LIMIT 1")


async def count_animes() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM animes")


async def list_animes(order: str, limit: int, offset: int = 0) -> list[Record]:
    """Ro'yxat: order = top | newest | oldest | id | title."""
    order_sql = _ORDERINGS.get(order)
    if order_sql is None:
        raise ValueError(f"Noma'lum tartib: {order!r}")
    # order_sql faqat yuqoridagi lug'atdan olinadi, foydalanuvchi matni emas
    return await db.fetch(
        f"SELECT * FROM animes ORDER BY {order_sql} LIMIT $1 OFFSET $2", limit, offset
    )


async def recent_since(since: datetime) -> list[Record]:
    """`since` dan keyin qo'shilgan animelar (Avto Post: oxirgi 24 soat)."""
    return await db.fetch(
        "SELECT * FROM animes WHERE created_at >= $1 ORDER BY created_at ASC, id ASC", since
    )


# ---------------------------------------------------------------------------
# Qidiruv
# ---------------------------------------------------------------------------
def _like_pattern(query: str) -> str:
    return "%" + escape_like(query.strip()) + "%"


async def search_by_title(query: str, limit: int, offset: int = 0) -> list[Record]:
    """Nom ichidan qidiradi. Nom boshida kelganlar yuqorida."""
    return await db.fetch(
        """
        SELECT * FROM animes
         WHERE title ILIKE $1
         ORDER BY strpos(lower(title), lower($2)), views DESC, id ASC
         LIMIT $3 OFFSET $4
        """,
        _like_pattern(query), query.strip(), limit, offset,
    )


async def count_by_title(query: str) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM animes WHERE title ILIKE $1", _like_pattern(query)
    )


async def list_genres() -> list[Record]:
    """Barcha janrlar va ulardagi animelar soni. Katta-kichik harf farqi hisobga olinmaydi."""
    return await db.fetch(
        """
        SELECT min(g) AS genre, COUNT(*) AS cnt
          FROM animes, unnest(genres) AS g
         GROUP BY lower(g)
         ORDER BY lower(min(g))
        """
    )


_GENRE_CONDITION = "EXISTS (SELECT 1 FROM unnest(genres) AS g WHERE lower(g) = lower($1))"


async def search_by_genre(genre: str, limit: int, offset: int = 0) -> list[Record]:
    return await db.fetch(
        f"SELECT * FROM animes WHERE {_GENRE_CONDITION} ORDER BY lower(title), id LIMIT $2 OFFSET $3",
        genre.strip(), limit, offset,
    )


async def count_by_genre(genre: str) -> int:
    return await db.fetchval(
        f"SELECT COUNT(*) FROM animes WHERE {_GENRE_CONDITION}", genre.strip()
    )


async def find_by_titles(names: Sequence[str | None], limit: int = 5) -> list[Record]:
    """Bir nechta nom variantidan (masalan trace.moe bergan romaji/inglizcha/yaponcha)
    bazadagi animeni topadi. To'liq mos kelganlar birinchi turadi."""
    cleaned = [n.strip() for n in names if n and n.strip()]
    if not cleaned:
        return []
    lowered = [n.lower() for n in cleaned]
    patterns = [_like_pattern(n) for n in cleaned if len(n) >= _MIN_FUZZY_LENGTH]
    return await db.fetch(
        """
        SELECT *, (lower(title) = ANY($1::text[])) AS exact_match
          FROM animes
         WHERE lower(title) = ANY($1::text[]) OR title ILIKE ANY($2::text[])
         ORDER BY exact_match DESC, views DESC, id ASC
         LIMIT $3
        """,
        lowered, patterns, limit,
    )


# ---------------------------------------------------------------------------
# Tahrirlash va o'chirish
# ---------------------------------------------------------------------------
async def update_field(anime_id: int, field: str, value: object) -> bool:
    """Bitta ustunni o'zgartiradi (title, year, genres, studio, poster_file_id)."""
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"Bu ustunni o'zgartirib bo'lmaydi: {field!r}")
    # `field` yuqoridagi ruxsat ro'yxatidan tekshirildi, shuning uchun f-string xavfsiz
    status = await db.execute(f"UPDATE animes SET {field} = $1 WHERE id = $2", value, anime_id)
    return rows_affected(status) > 0


async def set_vip(anime_id: int, is_vip: bool) -> bool:
    status = await db.execute("UPDATE animes SET is_vip = $2 WHERE id = $1", anime_id, is_vip)
    return rows_affected(status) > 0


async def delete_anime(anime_id: int) -> bool:
    """Animeni va uning barcha qismlarini o'chiradi (ON DELETE CASCADE)."""
    status = await db.execute("DELETE FROM animes WHERE id = $1", anime_id)
    return rows_affected(status) > 0


async def increment_views(anime_id: int) -> None:
    await db.execute("UPDATE animes SET views = views + 1 WHERE id = $1", anime_id)
