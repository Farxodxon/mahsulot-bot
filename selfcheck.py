"""
Bot'ni tekshirish (self-check) — barcha asosiy qismlarni sinovdan o'tkazadi.

    python selfcheck.py            # faqat lokal (SQLite) tekshiruvlari
    python selfcheck.py --postgres # Neon/PostgreSQL ulanishini ham tekshiradi

Tekshiriladi: importlar, DB qatlami, PDF, Excel, webhook/health server,
vaqt zonasi va yordamchi funksiyalar.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = "[ok]"
FAIL = "[FAIL]"
_results: list[tuple[bool, str]] = []

# Windows konsoli cp1251/cp1252 bo'lsa, kirill belgilar chiqmay qoladi —
# chiqishni UTF-8 ga o'tkazamiz (xatoga olib kelmasligi uchun).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def check(name: str, condition: bool, detail: str = "") -> bool:
    _results.append((condition, name))
    print(f"  {PASS if condition else FAIL} {name}" + (f" — {detail}" if detail else ""))
    return condition


async def check_database() -> None:
    print("\n[1] Ma'lumotlar bazasi (SQLite)")
    from services import db

    old_postgres = db.USE_POSTGRES
    old_path = db.DB_PATH
    tmp_path = Path(tempfile.gettempdir()) / "mahsulot_bot_selfcheck.db"
    if tmp_path.exists():
        tmp_path.unlink()

    db.USE_POSTGRES = False
    db.DB_PATH = str(tmp_path)
    try:
        await db.init_db()
        check("init_db() jadvallarni yaratdi", True)

        await db.set_worker_name(111, "Farxod")
        name = await db.get_worker_name(111)
        check("xodim ismi saqlandi/qaytarildi", name == "Farxod", str(name))

        rid = await db.insert_record(
            telegram_id=111,
            category="Стойкая крем-краска 3Д пакет *18",
            variant="7,0 Русый",
            quantity=48,
            worker="Farxod",
            notes="Birinchi partiya",
        )
        check("insert_record() id qaytardi", bool(rid), f"id={rid}")

        await db.insert_record(
            telegram_id=111,
            category="Стойкая крем-краска 3Д пакет *18",
            variant="7,0 Русый",
            quantity=12,
            worker="Farxod",
            notes="Birinchi partiya",
        )

        today = await db.get_today_records(111)
        check("get_today_records() 2 ta yozuv topdi", len(today) == 2, f"{len(today)} ta")

        batch = await db.get_batch_records(
            111, "Стойкая крем-краска 3Д пакет *18", "7,0 Русый", "Farxod"
        )
        check("get_batch_records() partiya yig'ildi", len(batch) == 2, f"{len(batch)} ta")

        notes = await db.get_frequent_notes(111)
        check("get_frequent_notes() taklif qaytardi", bool(notes))

        mine = await db.get_user_records(111)
        check("get_user_records() qaytardi", len(mine) == 2, f"{len(mine)} ta")

        ok = await db.check_connection()
        check("check_connection() ishladi", ok)

        await db.delete_record(rid)
        left = await db.get_user_records(111)
        check("delete_record() ishladi", len(left) == 1, f"{len(left)} ta")
    finally:
        db.USE_POSTGRES = old_postgres
        db.DB_PATH = old_path
        if tmp_path.exists():
            tmp_path.unlink()


async def check_postgres() -> None:
    print("\n[2] Ma'lumotlar bazasi (PostgreSQL)")
    from services import db

    if not db.DATABASE_URL:
        check("DATABASE_URL o'rnatilgan", False, "muhit o'zgaruvchisi yo'q")
        return
    ok = await db.check_connection()
    check("PostgreSQL'ga ulanish", ok)
    if ok:
        await db.init_db()
        check("init_db() (PostgreSQL) muvaffaqiyatli", True)


def check_documents() -> None:
    print("\n[3] PDF va Excel")
    from services.excel_service import build_excel
    from services.pdf_service import build_pallet_pages_pdf, build_record_pdf

    record = {
        "id": 1,
        "category": "Стойкая крем-краска 3Д пакет *18",
        "variant": "7,0 Русый",
        "quantity": 48,
        "date": "2026-10-21T18:30:00+05:00",
        "worker": "Farxod",
        "notes": "Yozuv tekshiruvi uchun",
    }
    pdf = build_record_pdf(record)
    check("build_record_pdf() PDF fayl yaratdi", pdf[:4] == b"%PDF", f"{len(pdf)} bayt")

    pages = build_pallet_pages_pdf([record, {**record, "id": 2}])
    check("build_pallet_pages_pdf() 2 sahifa yaratdi", pages[:4] == b"%PDF", f"{len(pages)} bayt")

    long_notes = build_record_pdf({**record, "notes": "Uzun izoh " * 200})
    check("uzun izoh PDF'da sig'di", long_notes[:4] == b"%PDF", f"{len(long_notes)} bayt")

    xlsx = build_excel([record])
    check("build_excel() fayl yaratdi", xlsx[:2] == b"PK", f"{len(xlsx)} bayt")


def check_helpers() -> None:
    print("\n[4] Yordamchi funksiyalar va vaqt")
    from utils.product_name_utils import short_category_name
    from utils.time_utils import now, parse_dt, today_str

    short = short_category_name("Стойкая крем-краска 3Д пакет *18")
    check("short_category_name() ishladi", short == "3Д пакет", short)

    stamp = now()
    check("now() vaqt zonasi bilan", stamp.tzinfo is not None, str(stamp))
    check("today_str() to'g'ri formatda", len(today_str()) == 10, today_str())

    parsed = parse_dt("2026-10-21T18:30:00+05:00")
    check("parse_dt() ISO satrni o'qidi", parsed.hour == 18, str(parsed))


async def check_server() -> None:
    print("\n[5] Webhook / health server")
    from server import WebhookServer

    class _StubBot:
        id = 1

    class _StubApp:
        def __init__(self) -> None:
            self.bot = _StubBot()
            self.update_queue: asyncio.Queue = asyncio.Queue()

    app = _StubApp()
    secret = "test-secret-token"
    server = WebhookServer(app, secret_token=secret, webhook_path="/webhook", port=18099)
    await server.start()
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:18099/health") as resp:
                body = await resp.json()
                check("GET /health -> 200", resp.status == 200, str(body))
                check("health ma'lumot bazasi holatini ko'rsatadi", body.get("database") in ("ok", "down"), str(body.get("database")))

            async with session.get("http://127.0.0.1:18099/") as resp:
                check("GET / -> 200", resp.status == 200)

            async with session.post("http://127.0.0.1:18099/webhook", json={}) as resp:
                check("POST /webhook (noto'g'ri secret) -> 403", resp.status == 403)

            payload = {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": 1792000000,
                    "chat": {"id": 1, "type": "private"},
                    "text": "test",
                },
            }
            async with session.post(
                "http://127.0.0.1:18099/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            ) as resp:
                check("POST /webhook (to'g'ri secret) -> 200", resp.status == 200)

            check("Update navbatga qo'shildi", app.update_queue.qsize() == 1)
    finally:
        await server.stop()


async def main() -> int:
    print("=" * 60)
    print("MAHSULOT BOT — TEKSHIRUV")
    print("=" * 60)

    print("\n[0] Importlar")
    for module in (
        "bot",
        "config",
        "server",
        "services.db",
        "services.pdf_service",
        "services.excel_service",
        "utils.product_name_utils",
        "utils.single_instance",
        "utils.time_utils",
    ):
        try:
            __import__(module)
            check(f"import {module}", True)
        except Exception as exc:  # noqa: BLE001
            check(f"import {module}", False, repr(exc))

    await check_database()
    if "--postgres" in sys.argv:
        await check_postgres()
    check_documents()
    check_helpers()
    await check_server()

    # Ochilgan Postgres pool'ini yopamiz (chiqishda xato chiqmasligi uchun).
    try:
        from services import db

        await db.close_db()
    except Exception:  # noqa: BLE001
        pass

    failed = [name for ok, name in _results if not ok]
    print("\n" + "=" * 60)
    print(f"Natija: {len(_results) - len(failed)}/{len(_results)} tekshiruv muvaffaqiyatli")
    if failed:
        print("Muvaffaqiyatsiz:")
        for name in failed:
            print(f"  - {name}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
