"""VIP obunalar va to'lov (chek) so'rovlari.

VIP huquqi `vip.expires_at` bo'yicha aniq vaqtda tugaydi. `is_vip()` har so'rovda
chaqirilishi mumkin (majburiy obuna tekshiruvi), shuning uchun natija xotirada
qisqa vaqt saqlanadi va VIP berilganda/olinganda darhol tozalanadi.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import asyncpg

from database.connection import db, rows_affected

Record = asyncpg.Record

_CACHE_TTL_SECONDS = 30.0
_CACHE_MAX_SIZE = 50_000
_cache: dict[int, tuple[bool, float]] = {}


def invalidate_cache(user_id: int | None = None) -> None:
    """Keshni tozalaydi (bitta foydalanuvchi yoki hammasi)."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


# ---------------------------------------------------------------------------
# VIP holati
# ---------------------------------------------------------------------------
async def is_vip(user_id: int) -> bool:
    now = time.monotonic()
    cached = _cache.get(user_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    active = bool(
        await db.fetchval(
            "SELECT EXISTS (SELECT 1 FROM vip WHERE user_id = $1 AND expires_at > now())",
            user_id,
        )
    )
    if len(_cache) >= _CACHE_MAX_SIZE:
        _cache.clear()
    _cache[user_id] = (active, now + _CACHE_TTL_SECONDS)
    return active


async def get_vip_info(user_id: int) -> Record | None:
    """Faol VIP bo'lsa qatorni (expires_at, plan...), aks holda None qaytaradi."""
    return await db.fetchrow(
        "SELECT * FROM vip WHERE user_id = $1 AND expires_at > now()", user_id
    )


async def grant_vip(user_id: int, days: int, plan: str, granted_by: int | None) -> datetime:
    """VIP beradi yoki mavjud VIP muddatini uzaytiradi. Yangi tugash vaqtini qaytaradi.

    Faol VIP bo'lsa, yangi muddat eski tugash vaqtiga qo'shiladi (kunlar yo'qolmaydi).
    """
    expires_at = await db.fetchval(
        """
        INSERT INTO vip (user_id, expires_at, plan, granted_by)
        VALUES ($1, now() + $2::interval, $3, $4)
        ON CONFLICT (user_id) DO UPDATE
           SET expires_at = GREATEST(vip.expires_at, now()) + $2::interval,
               plan       = EXCLUDED.plan,
               granted_by = EXCLUDED.granted_by
        RETURNING expires_at
        """,
        user_id, timedelta(days=days), plan, granted_by,
    )
    invalidate_cache(user_id)
    return expires_at


async def revoke_vip(user_id: int) -> bool:
    """VIP ni olib tashlaydi. Foydalanuvchida VIP bo'lgan bo'lsa True."""
    status = await db.execute("DELETE FROM vip WHERE user_id = $1", user_id)
    invalidate_cache(user_id)
    return rows_affected(status) > 0


async def pop_expired() -> list[Record]:
    """Muddati tugagan VIP yozuvlarini o'chiradi va (user_id, lang) ro'yxatini qaytaradi."""
    rows = await db.fetch(
        """
        WITH expired AS (
            DELETE FROM vip WHERE expires_at <= now() RETURNING user_id
        )
        SELECT e.user_id, COALESCE(u.lang, 'uz') AS lang
          FROM expired e
          LEFT JOIN users u ON u.user_id = e.user_id
        """
    )
    for row in rows:
        invalidate_cache(row["user_id"])
    return rows


async def count_active_vip() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM vip WHERE expires_at > now()")


# ---------------------------------------------------------------------------
# To'lovlar (chek orqali)
# ---------------------------------------------------------------------------
async def create_payment(user_id: int, plan: str, amount: int, receipt_file_id: str) -> int:
    """Yangi to'lov so'rovi (status: pending). So'rov ID sini qaytaradi."""
    return await db.fetchval(
        """
        INSERT INTO payments (user_id, plan, amount, receipt_file_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        user_id, plan, amount, receipt_file_id,
    )


async def get_payment(payment_id: int) -> Record | None:
    return await db.fetchrow("SELECT * FROM payments WHERE id = $1", payment_id)


async def resolve_payment(payment_id: int, status: str, reviewer_id: int) -> Record | None:
    """To'lovni tasdiqlaydi yoki rad etadi (status: approved | rejected).

    Faqat hali ko'rib chiqilmagan (pending) to'lov o'zgaradi. Agar boshqa admin allaqachon
    hal qilgan bo'lsa, None qaytaradi: shu tufayli bitta chek ikki marta tasdiqlanmaydi.
    """
    if status not in ("approved", "rejected"):
        raise ValueError(f"Noto'g'ri to'lov holati: {status!r}")
    return await db.fetchrow(
        """
        UPDATE payments
           SET status = $2, reviewed_by = $3, reviewed_at = now()
         WHERE id = $1 AND status = 'pending'
        RETURNING *
        """,
        payment_id, status, reviewer_id,
    )


async def count_pending_payments(user_id: int) -> int:
    """Foydalanuvchining ko'rib chiqilmagan cheklari soni (chek bilan spam qilishni cheklash uchun)."""
    return await db.fetchval(
        "SELECT COUNT(*) FROM payments WHERE user_id = $1 AND status = 'pending'", user_id
    )
