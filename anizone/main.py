"""
AniZone — ishga tushirish fayli.

Tartib:
  1. /health serveri (Render portni tez topishi uchun eng birinchi ishga tushadi)
  2. Baza: ulanish, jadvallar, boshlang'ich sozlamalar
  3. Fon vazifasi: muddati tugagan VIP larni tozalash
  4. Telegram polling (uzilsa, o'zi qayta ulanadi)

Ishga tushirish:  python main.py
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
from urllib.parse import urlsplit

try:
    from config import cfg
except Exception as exc:  # ConfigError yoki .env bilan bog'liq muammo
    print(f"SOZLAMA XATOSI: {exc}", file=sys.stderr)
    sys.exit(1)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError

from database import init_database
from database.connection import db
from handlers import register_routers
from services.health import start_health_server
from services.vip_expiry import vip_expiry_loop
from utils.logger import get_logger, setup_logging

log = get_logger("anizone")

_MAX_RETRY_DELAY = 60.0


class BotHolder:
    """Joriy Bot obyektini ushlab turadi (polling qayta ishga tushganda yangisi yaratiladi)."""

    def __init__(self) -> None:
        self.bot: Bot | None = None

    def create(self) -> Bot:
        self.bot = Bot(
            token=cfg.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        return self.bot

    def get(self) -> Bot | None:
        return self.bot

    async def close(self) -> None:
        bot, self.bot = self.bot, None
        if bot is None:
            return
        try:
            await bot.session.close()
        except Exception:
            log.debug("Bot sessiyasini yopishda xato (e'tiborsiz).", exc_info=True)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    register_routers(dp)
    return dp


async def init_database_forever() -> None:
    """Baza tayyor bo'lguncha urinadi: Neon vaqtincha javob bermasa, bot yiqilmaydi."""
    delay = 5.0
    while True:
        try:
            await init_database()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Bazani tayyorlashda xato. %.0f soniyadan keyin qayta uriniladi.", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_DELAY)


async def run_polling(dp: Dispatcher, holder: BotHolder) -> None:
    """Telegramdan yangilanishlarni oladi. Xato bo'lsa, kutib qayta ulanadi.

    Faqat to'xtatish signali (Ctrl+C yoki Render o'chirishi) kelganda tugaydi.
    """
    delay = 2.0
    while True:
        bot = holder.create()
        wait = delay
        try:
            me = await bot.get_me()
            log.info("Bot ulandi: @%s (id=%s)", me.username, me.id)
            # Avval o'rnatilgan webhook bo'lsa, polling ishlamaydi
            await bot.delete_webhook(drop_pending_updates=False)
            delay = 2.0
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            log.info("Polling to'xtatildi.")
            return
        except asyncio.CancelledError:
            raise
        except TelegramUnauthorizedError:
            log.critical(
                "BOT_TOKEN noto'g'ri yoki bekor qilingan. Renderda BOT_TOKEN ni yangilang. "
                "%.0f soniyadan keyin qayta uriniladi.", _MAX_RETRY_DELAY,
            )
            wait = _MAX_RETRY_DELAY
        except Exception:
            log.exception("Polling uzildi. %.0f soniyadan keyin qayta ulanadi.", wait)
        finally:
            await holder.close()

        await asyncio.sleep(wait)
        delay = min(delay * 2, _MAX_RETRY_DELAY)


async def main() -> None:
    db_password = urlsplit(cfg.database_url).password
    setup_logging(cfg.log_level, secrets=[cfg.bot_token, db_password, cfg.ai_api_key])
    log.info("AniZone ishga tushmoqda...")

    health_runner = None
    try:
        health_runner = await start_health_server(cfg.port)
    except OSError as exc:
        # Portni ochib bo'lmasa ham bot ishlayveradi, lekin UptimeRobot tekshira olmaydi
        log.error("Health serverni ishga tushirib bo'lmadi (port %d): %s", cfg.port, exc)

    holder = BotHolder()
    stop_event = asyncio.Event()
    expiry_task: asyncio.Task | None = None

    try:
        await init_database_forever()
        dp = build_dispatcher()
        expiry_task = asyncio.create_task(
            vip_expiry_loop(holder.get, stop_event), name="vip-expiry"
        )
        await run_polling(dp, holder)
    finally:
        log.info("AniZone to'xtatilmoqda...")
        stop_event.set()
        if expiry_task is not None:
            expiry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await expiry_task
        await holder.close()
        await db.close()
        if health_runner is not None:
            await health_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
