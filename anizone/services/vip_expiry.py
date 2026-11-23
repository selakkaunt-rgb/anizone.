"""
Muddati tugagan VIP larni tozalovchi fon vazifa.

VIP huquqi `expires_at` bo'yicha aniq vaqtda tugaydi (har so'rovda tekshiriladi).
Bu vazifa esa tugagan yozuvlarni bazadan o'chiradi, logga yozadi va foydalanuvchiga
xabar yuboradi. Tekshiruv oralig'i: config.VIP_EXPIRY_CHECK_SECONDS.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from config import VIP_EXPIRY_CHECK_SECONDS
from database import logs, users
from database import vip as vip_db
from texts import t
from utils.logger import get_logger

log = get_logger(__name__)


async def _notify(bot: Bot, user_id: int, lang: str) -> None:
    """Foydalanuvchiga VIP tugagani haqida xabar yuboradi. Xato bo'lsa, faqat logga yozadi."""
    try:
        await bot.send_message(user_id, t(lang, "vip_expired"))
    except TelegramForbiddenError:
        await users.set_blocked(user_id, True)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        try:
            await bot.send_message(user_id, t(lang, "vip_expired"))
        except TelegramAPIError as retry_exc:
            log.warning("VIP xabari yuborilmadi (user=%s): %s", user_id, retry_exc)
    except TelegramAPIError as exc:
        log.warning("VIP xabari yuborilmadi (user=%s): %s", user_id, exc)


async def process_expired(bot: Bot) -> int:
    """Bir marta tekshiradi. Tozalangan VIP lar sonini qaytaradi."""
    expired = await vip_db.pop_expired()
    for row in expired:
        user_id, lang = row["user_id"], row["lang"]
        await logs.add_log(user_id, "vip_expired", "VIP muddati tugadi")
        await _notify(bot, user_id, lang)
        await asyncio.sleep(0.05)  # Telegram limitiga yaqinlashmaslik uchun
    return len(expired)


async def vip_expiry_loop(get_bot: Callable[[], Bot | None], stop_event: asyncio.Event) -> None:
    """Dastur ishlayotgan vaqtda doimiy aylanadi. Hech qanday xato uni to'xtatmaydi.

    `get_bot` — hozirgi Bot obyektini qaytaradi (polling qayta ishga tushsa, Bot yangilanadi).
    Bot hali tayyor bo'lmasa, o'sha aylanish o'tkazib yuboriladi (xabar yo'qolmasligi uchun
    yozuvlar o'chirilmaydi).
    """
    log.info("VIP muddatini tekshirish vazifasi ishga tushdi (har %d soniyada).", VIP_EXPIRY_CHECK_SECONDS)
    while not stop_event.is_set():
        try:
            bot = get_bot()
            if bot is not None:
                count = await process_expired(bot)
                if count:
                    log.info("Muddati tugagan VIP lar tozalandi: %d ta.", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("VIP muddatini tekshirishda xato (keyingi aylanishda qayta uriniladi).")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=VIP_EXPIRY_CHECK_SECONDS)
        except asyncio.TimeoutError:
            pass
