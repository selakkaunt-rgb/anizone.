"""
Logger sozlamasi.

Hamma xabarlar stdout ga yoziladi: Renderda "Logs" bo'limida ko'rinadi.
Token, baza paroli va API kalit logga tushib qolsa, `***` bilan almashtiriladi
(traceback matnida ham).
"""
from __future__ import annotations

import logging
import sys
from typing import Iterable

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Juda ko'p xabar chiqaradigan kutubxona loggerlari
_NOISY_LOGGERS = ("aiogram.event", "asyncio", "aiohttp.access")


class _RedactingFormatter(logging.Formatter):
    """Tayyor log matnidagi maxfiy qiymatlarni yashiradi."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__(_LOG_FORMAT, _DATE_FORMAT)
        # Juda qisqa qiymatlar tasodifan oddiy so'zlarni ham yashirib yuborishi mumkin
        self._secrets = [s for s in secrets if s and len(s) >= 6]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, "***")
        return text


def setup_logging(level: str = "INFO", secrets: Iterable[str | None] = ()) -> None:
    """Root loggerni sozlaydi. Dastur boshida bir marta chaqiriladi."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_RedactingFormatter(s for s in secrets if s))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Modul uchun logger. Odatda `get_logger(__name__)`."""
    return logging.getLogger(name)
