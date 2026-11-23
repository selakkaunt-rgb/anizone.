"""
Kichik veb-server: `/health` manzili.

Render bepul tarifda veb-xizmat 15 daqiqa so'rovsiz qolsa, "uxlab" qoladi. UptimeRobot
shu manzilga har 5 daqiqada so'rov yuborib, botni uyg'oq ushlab turadi.

Bu manzil bazaga TEGMAYDI: aks holda har 5 daqiqada Neon ham uyg'onib turardi
va bepul soatlar tez tugardi.
"""
from __future__ import annotations

import time

from aiohttp import web

from utils.logger import get_logger

log = get_logger(__name__)

_STARTED_AT = time.monotonic()


async def _handle_health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "service": "anizone",
            "uptime_seconds": int(time.monotonic() - _STARTED_AT),
        }
    )


async def start_health_server(port: int, host: str = "0.0.0.0") -> web.AppRunner:
    """Serverni ishga tushiradi. To'xtatish uchun qaytgan obyektda `await runner.cleanup()`."""
    app = web.Application()
    # GET bilan birga HEAD ham avtomatik ishlaydi (UptimeRobot ko'pincha HEAD yuboradi)
    app.router.add_get("/", _handle_health)
    app.router.add_get("/health", _handle_health)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("Health server ishga tushdi: %s:%d (/health)", host, port)
    return runner
