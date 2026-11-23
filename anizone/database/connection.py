"""
Neon Postgres bilan ulanish (asyncpg pool).

Asosiy qoidalar:
  * Ulanish uzilsa, so'rov bir necha marta qayta uriniladi; kerak bo'lsa pool qaytadan quriladi.
  * Boshlang'ich ulanish baza javob berguncha urinaveradi (Neon "uxlab" yotgan bo'lishi mumkin).
  * Hamma so'rovlar parametrli ($1, $2...), SQL injection yo'q.

Boshqa modullar `from database.connection import db` qilib, `await db.fetch(...)` ishlatadi.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg
from asyncpg import exceptions as pgexc

from config import (
    DB_COMMAND_TIMEOUT,
    DB_CONNECT_TIMEOUT,
    DB_MAX_RETRIES,
    DB_POOL_MAX,
    DB_POOL_MIN,
    DB_RECONNECT_MAX_DELAY,
    cfg,
)
from utils.logger import get_logger

log = get_logger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Bazaga bir necha urinishdan keyin ham ulanib bo'lmadi."""


def _collect_retryable() -> tuple[type[BaseException], ...]:
    """Ulanish bilan bog'liq (vaqtincha) xatolar. Kutubxona versiyasida yo'q nomlar o'tkazib yuboriladi."""
    names = (
        "PostgresConnectionError",
        "ConnectionDoesNotExistError",
        "ConnectionFailureError",
        "CannotConnectNowError",
        "AdminShutdownError",
        "CrashShutdownError",
        "TooManyConnectionsError",
        "InterfaceError",
    )
    found = [getattr(pgexc, name) for name in names if hasattr(pgexc, name)]
    # OSError ichiga ConnectionError va TimeoutError ham kiradi
    return tuple(found) + (OSError, asyncio.TimeoutError)


_RETRYABLE = _collect_retryable()


def rows_affected(status: str) -> int:
    """`execute()` qaytargan 'UPDATE 3' kabi holat matnidan o'zgargan qatorlar sonini oladi."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0


class Database:
    """asyncpg pool ustidagi qatlam: qayta urinish va qayta ulanish bilan."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._connect_lock = asyncio.Lock()
        self._closed = False

    # ------------------------------------------------------------------
    # Ulanish
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Bazaga ulanadi. Ulana olmasa, ulanguncha qayta urinadi."""
        self._closed = False
        async with self._connect_lock:
            await self._create_pool_locked()

    async def _create_pool_locked(self) -> None:
        """Yangi pool quradi. `_connect_lock` ushlab turilgan bo'lishi shart."""
        old_pool, self._pool = self._pool, None
        if old_pool is not None:
            old_pool.terminate()

        delay = 1.0
        attempt = 0
        while not self._closed:
            attempt += 1
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=cfg.database_url,
                    min_size=DB_POOL_MIN,
                    max_size=DB_POOL_MAX,
                    command_timeout=DB_COMMAND_TIMEOUT,
                    timeout=DB_CONNECT_TIMEOUT,
                    # Neon pooler (pgbouncer) tayyorlangan so'rovlarni qo'llamaydi
                    statement_cache_size=0,
                    # Neon bo'sh ulanishlarni o'zi uzadi; biz ham ularni oldindan yopamiz
                    max_inactive_connection_lifetime=60.0,
                )
                log.info("Bazaga ulandi (urinish %d).", attempt)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(
                    "Bazaga ulanib bo'lmadi (urinish %d): %s. %.0f soniyadan keyin qayta uriniladi.",
                    attempt, exc, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, DB_RECONNECT_MAX_DELAY)
        raise DatabaseUnavailableError("Baza ulanishi yopilgan.")

    async def _reconnect(self, failed_pool: asyncpg.Pool | None) -> None:
        """Pool'ni qayta quradi. Boshqa vazifa allaqachon qayta ulagan bo'lsa, hech narsa qilmaydi."""
        async with self._connect_lock:
            current = self._pool
            if current is not None and current is not failed_pool and not current.is_closing():
                return
            log.warning("Baza ulanishi qayta o'rnatilmoqda...")
            await self._create_pool_locked()

    async def _get_pool(self) -> asyncpg.Pool:
        pool = self._pool
        if pool is None or pool.is_closing():
            await self._reconnect(pool)
            pool = self._pool
        if pool is None:
            raise DatabaseUnavailableError("Baza ulanishi mavjud emas.")
        return pool

    async def close(self) -> None:
        """Dastur to'xtaganda ulanishlarni yopadi."""
        self._closed = True
        pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            await asyncio.wait_for(pool.close(), timeout=10)
        except Exception:
            pool.terminate()
        log.info("Baza ulanishi yopildi.")

    async def ping(self) -> bool:
        """Baza javob berayotganini tekshiradi (qayta urinishsiz)."""
        try:
            pool = await self._get_pool()
            return (await pool.fetchval("SELECT 1", timeout=5)) == 1
        except Exception as exc:
            log.warning("Baza ping xatosi: %s", exc)
            return False

    # ------------------------------------------------------------------
    # So'rovlar (qayta urinish bilan)
    # ------------------------------------------------------------------
    async def _run(self, method: str, query: str, args: tuple[Any, ...], timeout: float | None) -> Any:
        delay = 0.5
        last_exc: BaseException | None = None
        for attempt in range(1, DB_MAX_RETRIES + 1):
            pool: asyncpg.Pool | None = None
            try:
                pool = await self._get_pool()
                return await getattr(pool, method)(query, *args, timeout=timeout)
            except _RETRYABLE as exc:
                last_exc = exc
                log.warning(
                    "Baza so'rovi xatosi (%s, urinish %d/%d): %s",
                    method, attempt, DB_MAX_RETRIES, exc,
                )
                if attempt == DB_MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)
                # Pool ba'zan o'zi tiklanadi; 2-urinishdan keyin ham bo'lmasa, qayta quramiz
                if attempt >= 2 and pool is not None:
                    await self._reconnect(pool)
        raise DatabaseUnavailableError(
            f"Baza {DB_MAX_RETRIES} urinishdan keyin ham javob bermadi."
        ) from last_exc

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """INSERT/UPDATE/DELETE. 'UPDATE 3' kabi holat matnini qaytaradi (`rows_affected` bilan o'qiladi)."""
        return await self._run("execute", query, args, timeout)

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[asyncpg.Record]:
        """Ko'p qatorli SELECT."""
        return await self._run("fetch", query, args, timeout)

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> asyncpg.Record | None:
        """Bitta qatorli SELECT; topilmasa None."""
        return await self._run("fetchrow", query, args, timeout)

    async def fetchval(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        """Bitta qiymat qaytaradi (birinchi qatorning birinchi ustuni)."""
        return await self._run("fetchval", query, args, timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Bir nechta so'rovni bitta tranzaksiyada bajarish uchun.

        Xato bo'lsa, hammasi bekor qilinadi. Ichidagi so'rovlar o'zi qayta urinilmaydi:
        ulanish uzilsa xato ko'tariladi va chaqiruvchi ushlaydi.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn


# Butun loyiha bo'ylab bitta umumiy obyekt
db = Database()
