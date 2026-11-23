"""Umumiy xato ushlagich: handlerdagi hech bir xato botni to'xtatmaydi, faqat logga yoziladi."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import ErrorEvent

from utils.logger import get_logger

log = get_logger(__name__)

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    log.error("Handlerda xato: %s", event.exception, exc_info=event.exception)
    return True  # xato "hal qilindi" deb belgilanadi, polling davom etadi
