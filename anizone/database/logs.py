"""`logs` jadvali: muhim amallar (VIP berish/olish, ban, xabar yuborish, kanal o'zgarishi) tarixi.

Owner bularni "Loglarni ko'rish" bo'limida ko'radi. Texnik xatolar esa bu yerga emas,
oddiy logger orqali Render loglariga yoziladi.
"""
from __future__ import annotations

import asyncpg

from database.connection import db
from utils.logger import get_logger

log = get_logger(__name__)

Record = asyncpg.Record

_MAX_ACTION_LENGTH = 64
_MAX_DETAILS_LENGTH = 1000


async def add_log(user_id: int | None, action: str, details: str = "") -> None:
    """Amalni yozadi. Hech qachon xato ko'tarmaydi: log yozilmasa, asosiy ish to'xtamasligi kerak.

    user_id — amalni BAJARGAN odam (masalan, VIP bergan owner). Kimga qilingani `details` da.
    """
    log.info("[%s] user=%s %s", action, user_id, details)
    try:
        await db.execute(
            "INSERT INTO logs (user_id, action, details) VALUES ($1, $2, $3)",
            user_id, action[:_MAX_ACTION_LENGTH], details[:_MAX_DETAILS_LENGTH],
        )
    except Exception:
        log.exception("Logni bazaga yozib bo'lmadi: %s", action)


async def get_logs(limit: int = 20, offset: int = 0, action: str | None = None) -> list[Record]:
    """Eng yangilari birinchi. `action` berilsa, faqat shu turdagi amallar."""
    if action is None:
        return await db.fetch(
            "SELECT * FROM logs ORDER BY id DESC LIMIT $1 OFFSET $2", limit, offset
        )
    return await db.fetch(
        "SELECT * FROM logs WHERE action = $1 ORDER BY id DESC LIMIT $2 OFFSET $3",
        action, limit, offset,
    )


async def count_logs(action: str | None = None) -> int:
    if action is None:
        return await db.fetchval("SELECT COUNT(*) FROM logs")
    return await db.fetchval("SELECT COUNT(*) FROM logs WHERE action = $1", action)
