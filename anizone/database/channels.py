"""`channels` jadvali: majburiy obuna kanallari (sub) va post yuboriladigan kanallar (post)."""
from __future__ import annotations

import asyncpg

from database.connection import db, rows_affected

Record = asyncpg.Record

KIND_SUB = "sub"
KIND_POST = "post"
_VALID_KINDS = (KIND_SUB, KIND_POST)


def _check_kind(kind: str) -> None:
    if kind not in _VALID_KINDS:
        raise ValueError(f"Noma'lum kanal turi: {kind!r}")


async def add_channel(chat_id: int, title: str, url: str | None, kind: str) -> Record:
    """Kanal qo'shadi. Shu turda bu kanal allaqachon bo'lsa, nomi va havolasini yangilaydi."""
    _check_kind(kind)
    row = await db.fetchrow(
        """
        INSERT INTO channels (chat_id, title, url, kind)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chat_id, kind) DO UPDATE
           SET title = EXCLUDED.title, url = EXCLUDED.url
        RETURNING *
        """,
        chat_id, title, url, kind,
    )
    assert row is not None
    return row


async def remove_channel(channel_id: int) -> bool:
    status = await db.execute("DELETE FROM channels WHERE id = $1", channel_id)
    return rows_affected(status) > 0


async def get_channel(channel_id: int) -> Record | None:
    return await db.fetchrow("SELECT * FROM channels WHERE id = $1", channel_id)


async def list_channels(kind: str) -> list[Record]:
    _check_kind(kind)
    return await db.fetch("SELECT * FROM channels WHERE kind = $1 ORDER BY id", kind)
