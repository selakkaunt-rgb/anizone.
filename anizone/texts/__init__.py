"""
Matnlar (o'zbek va rus). Hamma matnlar shu paketda turadi, kodda yozilmaydi.

Ishlatilishi:
    from texts import t
    await message.answer(t(lang, "vip_expired"))
    await message.answer(t(lang, "welcome", name="Ali"))   # matndagi {name} o'rniga qo'yiladi
"""
from __future__ import annotations

from config import DEFAULT_LANG, SUPPORTED_LANGS
from texts import ru, uz
from utils.logger import get_logger

log = get_logger(__name__)

_TEXTS: dict[str, dict[str, str]] = {"uz": uz.TEXTS, "ru": ru.TEXTS}


def normalize_lang(lang: str | None) -> str:
    """Noma'lum yoki bo'sh tilni standart tilga (o'zbek) aylantiradi."""
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def t(lang: str | None, key: str, **kwargs: object) -> str:
    """Matnni tilga qarab qaytaradi. Tilda yo'q bo'lsa o'zbekchasi, u ham yo'q bo'lsa kalitning o'zi."""
    lang = normalize_lang(lang)
    text = _TEXTS[lang].get(key)
    if text is None:
        text = _TEXTS[DEFAULT_LANG].get(key)
        if text is None:
            log.error("Matn topilmadi: %r", key)
            return key
        log.warning("'%s' matni %s tilida yo'q, o'zbekchasi ishlatildi.", key, lang)
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        log.exception("Matnni to'ldirib bo'lmadi: %r", key)
        return text
