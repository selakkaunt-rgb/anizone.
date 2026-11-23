"""
AniZone — sozlamalar.

Hamma maxfiy qiymatlar (token, parol, API kalit) FAQAT muhit o'zgaruvchilaridan o'qiladi
va kodda hech qachon yozilmaydi.

  * Renderda: Environment bo'limiga kiritiladi.
  * Kompyuterda sinash uchun: loyiha papkasida `.env` fayl yarating (`.env.example` ga qarang).

Tokenni almashtirsangiz, faqat Renderdagi BOT_TOKEN o'zgaruvchisini yangilash yetarli.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_DIR = Path(__file__).resolve().parent


class ConfigError(RuntimeError):
    """Muhit o'zgaruvchilari yetishmasa yoki noto'g'ri bo'lsa ko'tariladi."""


# ---------------------------------------------------------------------------
# .env o'qish (ixtiyoriy, faqat kompyuterda sinash uchun qulaylik)
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path) -> None:
    """`KEY=VALUE` ko'rinishidagi qatorlarni o'qiydi.

    Muhitda allaqachon mavjud o'zgaruvchilarni o'zgartirmaydi, shuning uchun
    Renderdagi qiymatlar har doim `.env` dan ustun turadi.
    """
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# DATABASE_URL ni asyncpg uchun moslash
# ---------------------------------------------------------------------------
# Neon ulanish havolasida ko'pincha `channel_binding=require` bo'ladi. asyncpg bu
# parametrni tanimaydi va "unrecognized configuration parameter" xatosini beradi.
_UNSUPPORTED_DSN_PARAMS = frozenset({"channel_binding"})


def normalize_database_url(url: str) -> str:
    """Neon havolasidan asyncpg tushunmaydigan parametrlarni olib tashlaydi."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql"):
        raise ConfigError(
            "DATABASE_URL 'postgresql://' yoki 'postgres://' bilan boshlanishi kerak."
        )
    if not parts.hostname:
        raise ConfigError("DATABASE_URL noto'g'ri: server manzili (host) topilmadi.")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _UNSUPPORTED_DSN_PARAMS
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


# ---------------------------------------------------------------------------
# Muhit o'zgaruvchilaridan olinadigan sozlamalar
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    # repr=False: tasodifan logga chiqib ketmasligi uchun
    bot_token: str = field(repr=False)
    owner_id: int
    database_url: str = field(repr=False)
    ai_api_key: str | None = field(repr=False)
    port: int
    log_level: str
    timezone: str


_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def load_config() -> Config:
    """Muhit o'zgaruvchilarini o'qib, tekshirib, Config qaytaradi."""
    _load_dotenv(BASE_DIR / ".env")

    required = ("BOT_TOKEN", "OWNER_ID", "DATABASE_URL")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ConfigError(
            "Quyidagi muhit o'zgaruvchilari kiritilmagan: "
            + ", ".join(missing)
            + ". Renderda Environment bo'limiga, kompyuterda `.env` faylga yozing."
        )

    bot_token = os.environ["BOT_TOKEN"].strip()
    if ":" not in bot_token or any(ch.isspace() for ch in bot_token):
        raise ConfigError(
            "BOT_TOKEN noto'g'ri ko'rinishda. U @BotFather bergan "
            "`123456:ABC...` ko'rinishidagi matn bo'lishi kerak."
        )

    try:
        owner_id = int(os.environ["OWNER_ID"].strip())
    except ValueError:
        raise ConfigError("OWNER_ID faqat raqamlardan iborat bo'lishi kerak.") from None
    if owner_id <= 0:
        raise ConfigError("OWNER_ID musbat son bo'lishi kerak.")

    port_raw = os.environ.get("PORT", "").strip() or "10000"
    try:
        port = int(port_raw)
    except ValueError:
        raise ConfigError("PORT faqat raqamlardan iborat bo'lishi kerak.") from None
    if not 1 <= port <= 65535:
        raise ConfigError("PORT 1 dan 65535 gacha bo'lishi kerak.")

    log_level = os.environ.get("LOG_LEVEL", "").strip().upper() or "INFO"
    if log_level not in _VALID_LOG_LEVELS:
        log_level = "INFO"

    timezone = os.environ.get("TIMEZONE", "").strip() or "Asia/Tashkent"
    ai_api_key = os.environ.get("AI_API_KEY", "").strip() or None

    return Config(
        bot_token=bot_token,
        owner_id=owner_id,
        database_url=normalize_database_url(os.environ["DATABASE_URL"]),
        ai_api_key=ai_api_key,
        port=port,
        log_level=log_level,
        timezone=timezone,
    )


# ---------------------------------------------------------------------------
# Doimiy qiymatlar (muhitga bog'liq emas)
# ---------------------------------------------------------------------------
SUPPORTED_LANGS = ("uz", "ru")
DEFAULT_LANG = "uz"

MENU_REPLY = "reply"    # pastki klaviatura
MENU_INLINE = "inline"  # xabar ostidagi inline tugmalar


@dataclass(frozen=True)
class Plan:
    """VIP tarifi. `key` callback_data (`vip_buy:<key>`) va to'lovlar jadvalida ishlatiladi."""

    key: str
    days: int
    default_price: int  # UZS; owner paneldan o'zgartirilsa, bazadagi qiymat ustun turadi


PLANS: dict[str, Plan] = {
    "3_month": Plan("3_month", 90, 50_000),
    "6_month": Plan("6_month", 180, 100_000),
    "3_year": Plan("3_year", 1095, 500_000),
}
# VIP ekranida tugmalar shu tartibda chiqadi
PLAN_DISPLAY_ORDER = ("3_year", "6_month", "3_month")

# Baza ulanishi
DB_POOL_MIN = 1
DB_POOL_MAX = 5
DB_COMMAND_TIMEOUT = 30.0      # bitta so'rov uchun soniya
DB_CONNECT_TIMEOUT = 30.0      # Neon "uxlab" yotgan bo'lsa, uyg'onishi uchun vaqt
DB_MAX_RETRIES = 4             # so'rov muvaffaqiyatsiz bo'lsa, necha marta qayta uriniladi
DB_RECONNECT_MAX_DELAY = 30.0  # qayta ulanishlar orasidagi eng uzun kutish

# VIP muddati tugaganini tekshirish oralig'i. VIP huquqi `expires_at` bo'yicha
# aniq vaqtda tugaydi; bu vazifa faqat yozuvni tozalaydi va xabar yuboradi.
VIP_EXPIRY_CHECK_SECONDS = 900

# Spamdan himoya: SPAM_WINDOW_SECONDS ichida SPAM_MAX_REQUESTS dan ko'p so'rov
# yuborgan foydalanuvchi SPAM_COOLDOWN_SECONDS soniya kutadi.
SPAM_MAX_REQUESTS = 5
SPAM_WINDOW_SECONDS = 10
SPAM_COOLDOWN_SECONDS = 30

# Ommaviy xabar yuborish tezligi (Telegram limitidan pastroq)
BROADCAST_PER_SECOND = 25

# `settings` jadvalidagi kalitlar
SETTING_CARD_INFO = "card_info"
SETTING_PRIVACY_URL = "privacy_url"
SETTING_OFFER_URL = "offer_url"
SETTING_MAIN_CHANNEL_URL = "main_channel_url"
SETTING_DEVELOPER_INFO = "developer_info"


def price_setting_key(plan_key: str) -> str:
    """Tarif narxi saqlanadigan `settings` kaliti, masalan `price_3_month`."""
    return f"price_{plan_key}"


DEFAULT_SETTINGS: dict[str, str] = {
    SETTING_CARD_INFO: "",
    SETTING_PRIVACY_URL: "",
    SETTING_OFFER_URL: "",
    SETTING_MAIN_CHANNEL_URL: "",
    SETTING_DEVELOPER_INFO: "",
    **{price_setting_key(p.key): str(p.default_price) for p in PLANS.values()},
}

# Import vaqtida bir marta yuklanadi. Xato bo'lsa, main.py tushunarli xabar chiqaradi.
cfg: Config = load_config()
