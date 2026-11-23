"""Umumiy yordamchi funksiyalar: vaqt, matn va ro'yxatlar bilan ishlash."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, Sequence, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

T = TypeVar("T")


def _load_timezone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # Windowsda `tzdata` o'rnatilmagan bo'lsa shunday bo'ladi (requirements.txt da bor).
        log.warning("'%s' vaqt mintaqasi topilmadi, UTC+5 ishlatiladi.", name)
        return timezone(timedelta(hours=5))


TZ = _load_timezone(cfg.timezone)


# ---------------------------------------------------------------------------
# Vaqt
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    """Hozirgi vaqt (UTC, tz-aware)."""
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Hozirgi vaqt bot mintaqasida (Asia/Tashkent)."""
    return datetime.now(TZ)


def today_start_utc() -> datetime:
    """Mahalliy "bugun" boshlanishi (00:00), UTC ko'rinishida. "Bugungi yangi foydalanuvchilar" uchun."""
    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def to_local(value: datetime) -> datetime:
    """Bazadan kelgan vaqtni mahalliy mintaqaga o'tkazadi."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ)


def format_dt(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Vaqtni mahalliy mintaqada chiroyli ko'rsatadi. None bo'lsa, '—'."""
    if value is None:
        return "—"
    return to_local(value).strftime(fmt)


# ---------------------------------------------------------------------------
# Matn va ro'yxatlar
# ---------------------------------------------------------------------------
def escape_like(text: str) -> str:
    """ILIKE qidiruvi uchun `\\`, `%` va `_` belgilarini oddiy belgi qiladi.

    Aks holda foydalanuvchi `%` yozib hamma yozuvni topib olishi mumkin.
    PostgreSQL da LIKE uchun standart escape belgisi — teskari chiziq (`\\`).
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    """Matnni `limit` belgigacha qisqartiradi."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(suffix):
        return text[:limit]
    return text[: limit - len(suffix)] + suffix


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Ro'yxatni `size` tadan bo'laklarga ajratadi."""
    if size <= 0:
        raise ValueError("size musbat bo'lishi kerak")
    for index in range(0, len(items), size):
        yield items[index:index + size]


def safe_int(value: object, default: int | None = None) -> int | None:
    """int ga o'tkazadi, bo'lmasa `default` qaytaradi."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
