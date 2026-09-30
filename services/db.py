"""
Ma'lumotlar bazasi bilan ishlash (SQLite, sinxron — bot uchun bu yetarli).
"""
import sqlite3
from datetime import datetime, date
from contextlib import contextmanager

from config import DB_PATH


def init_db():
    with _connect() as conn:
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


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Xodim ismi (har bir Telegram foydalanuvchisi uchun bitta marta so'raladi)
# ---------------------------------------------------------------------
def get_worker_name(telegram_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT name FROM workers WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row["name"] if row else None


def set_worker_name(telegram_id: int, name: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO workers (telegram_id, name) VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET name = excluded.name
            """,
            (telegram_id, name),
        )
        conn.commit()


# ---------------------------------------------------------------------
# Yozuvlar (palletlar)
# ---------------------------------------------------------------------
def insert_record(
    telegram_id: int,
    category: str,
    variant: str,
    quantity: int,
    worker: str,
    notes: str = "",
    when: datetime | None = None,
) -> int:
    when = when or datetime.now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO records (telegram_id, category, variant, quantity, date, worker, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, category, variant, quantity, when.isoformat(), worker, notes),
        )
        conn.commit()
        return cur.lastrowid


def get_records_by_ids(ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        return conn.execute(
            f"SELECT * FROM records WHERE id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()


def get_today_records(telegram_id: int) -> list[sqlite3.Row]:
    today_str = date.today().isoformat()
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM records
            WHERE telegram_id = ? AND date LIKE ?
            ORDER BY id DESC
            """,
            (telegram_id, f"{today_str}%"),
        ).fetchall()


def get_all_records(limit: int = 2000) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM records ORDER BY date DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()


def get_user_records(telegram_id: int, limit: int = 2000) -> list[sqlite3.Row]:
    """Faqat shu foydalanuvchining o'z yozuvlari."""
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM records
            WHERE telegram_id = ?
            ORDER BY date DESC, id DESC LIMIT ?
            """,
            (telegram_id, limit),
        ).fetchall()


def get_batch_records(telegram_id: int, category: str, variant: str, worker: str) -> list[sqlite3.Row]:
    """Bir 'partiya' — shu foydalanuvchining shu mahsulot, shu rang va shu ishchi
    tomonidan AYNAN shu kunda qo'shilgan barcha palletlari («Yana qo'shish» bilan
    to'plangan yozuvlar bitta PDF da chiqishi uchun)."""
    today_str = date.today().isoformat()
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM records
            WHERE telegram_id = ? AND category = ? AND variant = ? AND worker = ? AND date LIKE ?
            ORDER BY id
            """,
            (telegram_id, category, variant, worker, f"{today_str}%"),
        ).fetchall()


def get_records_by_worker_today(telegram_id: int) -> list[sqlite3.Row]:
    """Shu foydalanuvchining bugungi barcha yozuvlari — 'Jamlab PDF' uchun."""
    return get_today_records(telegram_id)


def delete_record(record_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()
