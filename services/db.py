"""
Ma'lumotlar bazasi bilan ishlash (async API, sinxron DB driver).

Ikki rejim qo'llab-quvvatlanadi:
  * `DATABASE_URL` o'rnatilgan bo'lsa — PostgreSQL (Neon) va ulanish pool'i.
  * Aks holda — SQLite (mahsulot_bot.db fayli, lokal ishlash uchun).

Ikkala rejimda ham tashqi API bir xil va `await` bilan chaqiriladi:
    name = await db.get_worker_name(telegram_id)

Qatorlar `row["ustun_nomi"]` orqali o'qiladi (Postgres'da `dict_row`,
SQLite'da `sqlite3.Row`).

Sinxron driver ataylab tanlangan: psycopg'ning async rejimi Windows'dagi
ProactorEventLoop bilan mos emas. Barcha DB so'rovlari `asyncio.to_thread`
orqali worker thread'da bajariladi — event loop bloklanmaydi.
"""
import asyncio
import sqlite3
from datetime import date, datetime

from config import DB_PATH, DATABASE_URL

# --- Rejim tanlash -------------------------------------------------------
USE_POSTGRES = bool(DATABASE_URL)

_pool = None


def _get_pool():
    """Postgres ulanish pool'i (sinxron, thread-safe)."""
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=30.0,
            kwargs={"connect_timeout": 20},
            open=False,
        )
        pool.open(wait=True, timeout=30)
        _pool = pool
    return _pool


def _sql(query: str) -> str:
    """SQLite `?` placeholder'larini Postgres `%s` ga tarjima qiladi."""
    return query.replace("?", "%s") if USE_POSTGRES else query


# ---------------------------------------------------------------------
# Sinxron yordamchilar (worker thread ichida ishlaydi)
# ---------------------------------------------------------------------
def _sqlite_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_fetch_all(sql: str, params: tuple) -> list:
    conn = _sqlite_connect()
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description is not None else []
    finally:
        conn.close()


def _sqlite_execute(sql: str, params: tuple) -> int:
    conn = _sqlite_connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def _sqlite_init_db():
    conn = _sqlite_connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                variant TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                date TEXT NOT NULL,
                worker TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _pg_fetch_all(sql: str, params: tuple) -> list:
    from psycopg.rows import dict_row

    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_sql(sql), params)
            return cur.fetchall() if cur.description is not None else []


def _pg_execute(sql: str, params: tuple) -> int:
    """SQL bajaradi. `RETURNING id` bo'lsa — yangi id qaytaradi, aks holda 0."""
    from psycopg.rows import dict_row

    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_sql(sql), params)
            if cur.description is not None:
                rows = cur.fetchall()
                if rows and "id" in rows[0]:
                    return int(rows[0]["id"])
    return 0


def _pg_init_db():
    # Advisory lock bilan DDL serializatsiyalanadi: bir nechta instance bir vaqtda
    # ishga tushsa, `CREATE TABLE IF NOT EXISTS` race'ga tushib unique violation
    # berishi mumkin.
    with _get_pool().connection() as conn:
        conn.execute("SELECT pg_advisory_lock(424242)")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workers (
                    telegram_id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    category TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_user_date "
                "ON records (telegram_id, date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_batch "
                "ON records (telegram_id, category, variant, worker, date)"
            )
            conn.commit()
        finally:
            conn.execute("SELECT pg_advisory_unlock(424242)")


# ---------------------------------------------------------------------
# Async o'ram (sinxron so'rovlarni worker thread'da bajaradi)
# ---------------------------------------------------------------------
async def _fetch_all(sql: str, params: tuple = ()) -> list:
    if USE_POSTGRES:
        return await asyncio.to_thread(_pg_fetch_all, sql, params)
    return await asyncio.to_thread(_sqlite_fetch_all, sql, params)


async def _execute(sql: str, params: tuple = ()) -> int:
    if USE_POSTGRES:
        return await asyncio.to_thread(_pg_execute, sql, params)
    return await asyncio.to_thread(_sqlite_execute, sql, params)


async def close_db() -> None:
    """Postgres poolini yopadi (bot to'xtayotganda chaqiriladi)."""
    global _pool
    if _pool is not None:
        await asyncio.to_thread(_pool.close)
        _pool = None


# ---------------------------------------------------------------------
# Jadvallar
# ---------------------------------------------------------------------
async def init_db():
    if USE_POSTGRES:
        await asyncio.to_thread(_pg_init_db)
    else:
        await asyncio.to_thread(_sqlite_init_db)


# ---------------------------------------------------------------------
# Xodim ismi (har bir Telegram foydalanuvchisi uchun bitta marta so'raladi)
# ---------------------------------------------------------------------
async def get_worker_name(telegram_id: int) -> str | None:
    rows = await _fetch_all(
        "SELECT name FROM workers WHERE telegram_id = ?", (telegram_id,)
    )
    return rows[0]["name"] if rows else None


async def set_worker_name(telegram_id: int, name: str) -> None:
    await _execute(
        """
        INSERT INTO workers (telegram_id, name) VALUES (?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET name = excluded.name
        """,
        (telegram_id, name),
    )


# ---------------------------------------------------------------------
# Yozuvlar (palletlar)
# ---------------------------------------------------------------------
async def insert_record(
    telegram_id: int,
    category: str,
    variant: str,
    quantity: int,
    worker: str,
    notes: str = "",
    when: datetime | None = None,
) -> int:
    when = when or datetime.now()
    if USE_POSTGRES:
        return await _execute(
            """
            INSERT INTO records (telegram_id, category, variant, quantity, date, worker, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (telegram_id, category, variant, quantity, when.isoformat(), worker, notes),
        )
    return await _execute(
        """
        INSERT INTO records (telegram_id, category, variant, quantity, date, worker, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (telegram_id, category, variant, quantity, when.isoformat(), worker, notes),
    )


async def get_records_by_ids(ids: list[int]) -> list:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return await _fetch_all(
        f"SELECT * FROM records WHERE id IN ({placeholders}) ORDER BY id", tuple(ids)
    )


async def get_today_records(telegram_id: int) -> list:
    today_str = date.today().isoformat()
    return await _fetch_all(
        """
        SELECT * FROM records
        WHERE telegram_id = ? AND date LIKE ?
        ORDER BY id DESC
        """,
        (telegram_id, f"{today_str}%"),
    )


async def get_all_records(limit: int = 2000) -> list:
    return await _fetch_all(
        "SELECT * FROM records ORDER BY date DESC, id DESC LIMIT ?", (limit,)
    )


async def get_user_records(telegram_id: int, limit: int = 2000) -> list:
    """Faqat shu foydalanuvchining o'z yozuvlari."""
    return await _fetch_all(
        """
        SELECT * FROM records
        WHERE telegram_id = ?
        ORDER BY date DESC, id DESC LIMIT ?
        """,
        (telegram_id, limit),
    )


async def get_frequent_notes(telegram_id: int, limit: int = 5) -> list:
    """Shu foydalanuvchining eng ko'p yozgan izohlari (taklif tugmalari uchun).
    Eng ko'p qo'llanganidan kamayish tartibida; teng bo'lsa — eng oxirgi ishlatilgan."""
    return await _fetch_all(
        """
        SELECT notes, COUNT(*) AS cnt
        FROM records
        WHERE telegram_id = ? AND TRIM(notes) <> ''
        GROUP BY notes
        ORDER BY cnt DESC, MAX(date) DESC
        LIMIT ?
        """,
        (telegram_id, limit),
    )


async def get_batch_records(telegram_id: int, category: str, variant: str, worker: str) -> list:
    """Bir 'partiya' — shu foydalanuvchining shu mahsulot, shu rang va shu ishchi
    tomonidan AYNAN shu kunda qo'shilgan barcha palletlari («Yana qo'shish» bilan
    to'plangan yozuvlar bitta PDF da chiqishi uchun)."""
    today_str = date.today().isoformat()
    return await _fetch_all(
        """
        SELECT * FROM records
        WHERE telegram_id = ? AND category = ? AND variant = ? AND worker = ? AND date LIKE ?
        ORDER BY id
        """,
        (telegram_id, category, variant, worker, f"{today_str}%"),
    )


async def get_records_by_worker_today(telegram_id: int) -> list:
    """Shu foydalanuvchining bugungi barcha yozuvlari — 'Jamlab PDF' uchun."""
    return await get_today_records(telegram_id)


async def delete_record(record_id: int) -> None:
    await _execute("DELETE FROM records WHERE id = ?", (record_id,))
