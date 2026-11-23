"""
Handlerlar. Har bir bosqichda yangi routerlar shu yerda ulanadi.

Tartib muhim: aiogram routerlarni qo'shilgan tartibida tekshiradi.
"""
from __future__ import annotations

from aiogram import Dispatcher


def register_routers(dp: Dispatcher) -> None:
    """Hamma routerlarni dispatcherga ulaydi."""
    from handlers.errors import router as errors_router

    dp.include_router(errors_router)
    # Keyingi bosqichlarda: user, admin, owner routerlari shu yerga qo'shiladi
