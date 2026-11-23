"""
Baza jadvallari va migratsiyalar.

Har bir migratsiya raqamli versiyaga ega va faqat bir marta bajariladi (`schema_version`
jadvalida qayd etiladi). Keyinchalik jadvalga ustun qo'shish kerak bo'lsa, mavjud
migratsiyani O'ZGARTIRMANG: ro'yxat oxiriga yangisini qo'shing.

Bir vaqtda ikkita nusxa (masalan Render yangi versiyani ishga tushirayotganda) migratsiya
qilsa, advisory lock navbat bilan bajarilishini ta'minlaydi.
"""
from __future__ import annotations

from dataclasses import dataclass

from database.connection import db
from utils.logger import get_logger

log = get_logger(__name__)

_MIGRATION_LOCK_KEY = 7_000_001


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


_INITIAL_SCHEMA = (
    # ---------------- users ----------------
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id      BIGINT PRIMARY KEY,
        username     TEXT,
        first_name   TEXT NOT NULL DEFAULT '',
        nickname     TEXT,
        lang         TEXT CHECK (lang IN ('uz', 'ru')),
        menu_type    TEXT NOT NULL DEFAULT 'reply' CHECK (menu_type IN ('reply', 'inline')),
        ai_memory    BOOLEAN NOT NULL DEFAULT TRUE,
        is_banned    BOOLEAN NOT NULL DEFAULT FALSE,
        ban_reason   TEXT,
        is_blocked   BOOLEAN NOT NULL DEFAULT FALSE,
        joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_active  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_joined_at ON users (joined_at)",
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users (lower(username))",
    # ---------------- animes ----------------
    """
    CREATE TABLE IF NOT EXISTS animes (
        id              INTEGER PRIMARY KEY CHECK (id > 0),
        title           TEXT NOT NULL,
        year            INTEGER,
        genres          TEXT[] NOT NULL DEFAULT '{}',
        studio          TEXT,
        poster_file_id  TEXT,
        is_vip          BOOLEAN NOT NULL DEFAULT FALSE,
        views           INTEGER NOT NULL DEFAULT 0,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_animes_created_at ON animes (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_animes_views ON animes (views DESC)",
    "CREATE INDEX IF NOT EXISTS idx_animes_title_lower ON animes (lower(title))",
    "CREATE INDEX IF NOT EXISTS idx_animes_genres ON animes USING GIN (genres)",
    # ---------------- episodes ----------------
    # UNIQUE (anime_id, number): 37-qism keyin qo'shilsa ham o'z joyiga tushadi,
    # qism o'chirilsa qolganlarning raqami o'zgarmaydi.
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id              SERIAL PRIMARY KEY,
        anime_id        INTEGER NOT NULL REFERENCES animes (id) ON DELETE CASCADE,
        number          INTEGER NOT NULL CHECK (number > 0),
        file_id         TEXT NOT NULL,
        file_unique_id  TEXT,
        is_vip          BOOLEAN NOT NULL DEFAULT FALSE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT episodes_anime_number_key UNIQUE (anime_id, number)
    )
    """,
    # ---------------- vip ----------------
    """
    CREATE TABLE IF NOT EXISTS vip (
        user_id     BIGINT PRIMARY KEY,
        expires_at  TIMESTAMPTZ NOT NULL,
        plan        TEXT NOT NULL DEFAULT 'manual',
        granted_by  BIGINT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vip_expires_at ON vip (expires_at)",
    # ---------------- channels ----------------
    # kind: 'sub' = majburiy obuna kanali, 'post' = post yuboriladigan kanal
    """
    CREATE TABLE IF NOT EXISTS channels (
        id        SERIAL PRIMARY KEY,
        chat_id   BIGINT NOT NULL,
        title     TEXT NOT NULL DEFAULT '',
        url       TEXT,
        kind      TEXT NOT NULL CHECK (kind IN ('sub', 'post')),
        added_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT channels_chat_kind_key UNIQUE (chat_id, kind)
    )
    """,
    # ---------------- admins ----------------
    # Owner bu jadvalda turmaydi: u OWNER_ID muhit o'zgaruvchisidan olinadi.
    """
    CREATE TABLE IF NOT EXISTS admins (
        user_id   BIGINT PRIMARY KEY,
        added_by  BIGINT,
        added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ---------------- logs ----------------
    """
    CREATE TABLE IF NOT EXISTS logs (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT,
        action      TEXT NOT NULL,
        details     TEXT NOT NULL DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_logs_action ON logs (action)",
    # ---------------- payments ----------------
    """
    CREATE TABLE IF NOT EXISTS payments (
        id               SERIAL PRIMARY KEY,
        user_id          BIGINT NOT NULL,
        plan             TEXT NOT NULL,
        amount           INTEGER NOT NULL,
        receipt_file_id  TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected')),
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        reviewed_by      BIGINT,
        reviewed_at      TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_payments_user_status ON payments (user_id, status)",
    # ---------------- settings ----------------
    """
    CREATE TABLE IF NOT EXISTS settings (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL DEFAULT ''
    )
    """,
    # ---------------- ai_history ----------------
    """
    CREATE TABLE IF NOT EXISTS ai_history (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT NOT NULL,
        role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content     TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_history_user ON ai_history (user_id, id)",
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "boshlang'ich jadvallar", _INITIAL_SCHEMA),
)


async def run_migrations() -> None:
    """Hali bajarilmagan migratsiyalarni tartib bilan bajaradi.

    Hammasi bitta tranzaksiyada: xato bo'lsa, baza avvalgi holatida qoladi.
    """
    async with db.transaction() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _MIGRATION_LOCK_KEY)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        rows = await conn.fetch("SELECT version FROM schema_version")
        applied = {row["version"] for row in rows}

        pending = [m for m in MIGRATIONS if m.version not in applied]
        if not pending:
            log.info("Baza sxemasi dolzarb (versiya %d).", max(applied, default=0))
            return

        for migration in sorted(pending, key=lambda m: m.version):
            log.info("Migratsiya %d bajarilmoqda: %s", migration.version, migration.name)
            for statement in migration.statements:
                await conn.execute(statement)
            await conn.execute(
                "INSERT INTO schema_version (version, name) VALUES ($1, $2)",
                migration.version, migration.name,
            )
        log.info("Migratsiyalar tugadi (%d ta).", len(pending))
