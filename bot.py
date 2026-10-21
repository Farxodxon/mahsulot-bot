"""
Ishlab chiqarilgan tayyor mahsulotni qayd qilish uchun Telegram bot.

Ishga tushirish:
    1) requirements.txt dagi paketlarni o'rnating: pip install -r requirements.txt
    2) TELEGRAM_BOT_TOKEN ni muhit o'zgaruvchisi yoki `.env` fayliga yozing
    3) python bot.py

Rejimlar (avtomatik tanlanadi):
    * Webhook — serverda (Render). `WEBHOOK_URL` yoki `RENDER_EXTERNAL_URL`
      bo'lsa ishlatiladi. Bot `PORT` ga ulanadi, `/health` endpointi ishlaydi.
    * Polling — lokalda. Telegram serveriga so'rov yuborib yangilik oladi.

Asosiy imkoniyatlar:
    - Mahsulot tanlash (kategoriya -> rang/variant), palletdagi soni, izoh
    - Har bir yozuv uchun katta harfli PDF hujjat (oq-qora printerga mos)
    - Bir kunlik barcha yozuvlarni bitta PDF faylga jamlash (har biri o'z sahifasida)
    - Barcha yozuvlarni Excel (.xlsx) qilib chiqarish
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import logging.handlers
import os
import signal
import sys
import time

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Conflict, Forbidden, NetworkError, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from data.products_data import PRODUCT_CATEGORIES
from server import WebhookServer
from services import db
from services.excel_service import build_excel
from services.pdf_service import build_pallet_pages_pdf, build_record_pdf
from utils.product_name_utils import short_category_name
from utils.single_instance import SingleInstanceLock
from utils.time_utils import now, parse_dt

logger = logging.getLogger(__name__)

VARIANTS_PER_PAGE = 8

# Suhbat holatlari
(
    ASK_NAME,
    CHOOSING_CATEGORY,
    CHOOSING_VARIANT,
    ASK_WORKER,
    ENTERING_QTY,
    ENTERING_NOTES_TEXT,
) = range(6)


# =======================================================================
# Loglar
# =======================================================================
class TokenMaskingFilter(logging.Filter):
    """Loglarda bot tokenini yashiradi (httpx API URL'larida chiqib turibdi)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_BOT_TOKEN in message:
            record.msg = message.replace(config.TELEGRAM_BOT_TOKEN, "***TOKEN***")
            record.args = ()
        return True


def _setup_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # Windows konsoli cp1252 bo'lishi mumkin — chiqishni UTF-8 qilamiz.
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    if config.LOG_FILE and config.LOG_TO_FILE:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning("Log fayli yaratilmadi (%s): %r", config.LOG_FILE, exc)

    for name in ("httpx", "telegram", "apscheduler"):
        logging.getLogger(name).addFilter(TokenMaskingFilter())


# =======================================================================
# Klaviaturalar
# =======================================================================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("➕ Yangi yozuv", callback_data="menu:new")],
        [InlineKeyboardButton("📋 Bugungi yozuvlarim", callback_data="menu:today")],
        [InlineKeyboardButton("🖨 Bugungi hujjat (PDF)", callback_data="menu:today_pdf")],
        [InlineKeyboardButton("📊 Excel eksport (barchasi)", callback_data="menu:export_excel")],
        [InlineKeyboardButton("🖨 PDF eksport (barchasi)", callback_data="menu:export_pdf")],
        [InlineKeyboardButton("👤 Ismni o'zgartirish", callback_data="menu:setname")],
    ]
    return InlineKeyboardMarkup(rows)


def category_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i, cat in enumerate(PRODUCT_CATEGORIES):
        rows.append([InlineKeyboardButton(short_category_name(cat["name"]), callback_data=f"cat:{i}")])
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def variant_keyboard(cat_index: int, page: int) -> InlineKeyboardMarkup:
    items = PRODUCT_CATEGORIES[cat_index]["items"]
    start = page * VARIANTS_PER_PAGE
    end = start + VARIANTS_PER_PAGE
    page_items = items[start:end]

    rows = []
    for i, item in enumerate(page_items, start=start):
        rows.append([InlineKeyboardButton(item, callback_data=f"var:{i}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"vpage:{page - 1}"))
    if end < len(items):
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"vpage:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⬅️ Kategoriyalar", callback_data="back:cat")])
    return InlineKeyboardMarkup(rows)


def notes_suggest_keyboard(suggestions: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, note in enumerate(suggestions):
        label = note if len(note) <= 32 else note[:31] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"note_pick:{i}")])
    return InlineKeyboardMarkup(rows)


def after_save_keyboard(record_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖨 Ushbu pallet uchun PDF", callback_data=f"pdf:{record_id}")],
            [InlineKeyboardButton("➕ Yana shu mahsulotdan qo'shish", callback_data="quick_add")],
            [InlineKeyboardButton("🆕 Boshqa mahsulot", callback_data="menu:new")],
            [InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu:main")],
        ]
    )


# =======================================================================
# Yordamchi funksiyalar
# =======================================================================
TELEGRAM_TEXT_LIMIT = 4096


def _split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Uzun matnni Telegram limitidan (4096) kichik bo'laklarga ajratadi."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)

    # Bitta qator butun limitdan uzun bo'lsa — bo'laklarga kesamiz.
    fixed: list[str] = []
    for chunk in chunks:
        while len(chunk) > limit:
            fixed.append(chunk[:limit])
            chunk = chunk[limit:]
        if chunk:
            fixed.append(chunk)
    return fixed or [""]


async def _delete_clicked(query) -> None:
    try:
        await query.message.delete()
    except (BadRequest, Forbidden, AttributeError):
        pass


async def _next_step(query, text: str, reply_markup=None):
    """Eski xabarni o'chirib, yangi xabar yuboradi (toza oqim)."""
    chat = query.message.chat
    await _delete_clicked(query)
    try:
        return await chat.send_message(text, reply_markup=reply_markup)
    except TelegramError:
        return await chat.send_message(text)


async def _send(chat, text: str, reply_markup=None):
    """Xabar yuboradi (xatolik bo'lsa ham urinishdan qaytmaydi)."""
    try:
        return await chat.send_message(text, reply_markup=reply_markup)
    except TelegramError as exc:
        logger.error("Xabar yuborilmadi: %r", exc)
        return None


async def _send_document(chat, data: bytes, filename: str, caption: str) -> None:
    try:
        await chat.send_document(document=data, filename=filename, caption=caption)
    except TelegramError as exc:
        logger.error("Fayl yuborilmadi: %r", exc)
        await _send(chat, "Hujjatni yuborishda xatolik. Iltimos, qayta urinib ko'ring.")


# =======================================================================
# /start va ism so'rash
# =======================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    name = await db.get_worker_name(telegram_id)
    if name:
        await _send(
            update.effective_chat,
            f"Salom, {name}! Nima qilamiz?",
            main_menu_keyboard(),
        )
        return ConversationHandler.END
    await _send(
        update.effective_chat,
        "Assalomu alaykum! Ishlab chiqarish botiga xush kelibsiz.\n\n"
        "Avval ismingizni kiriting (bu yozuvlarda \"Kim chiqargan\" sifatida ishlatiladi):",
    )
    return ASK_NAME


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(
        update.effective_chat,
        "Buyruqlar:\n"
        "/start — bosh menyu\n"
        "/cancel — joriy amalni to'xtatish\n"
        "/help — yordam\n\n"
        "Bosh menyudan: yangi yozuv, bugungi yozuvlar, PDF/Excel eksport.",
    )


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await _send(update.effective_chat, "Iltimos, ismingizni kiriting:")
        return ASK_NAME
    await db.set_worker_name(update.effective_user.id, name)
    await _send(
        update.effective_chat,
        f"Rahmat, {name}! Endi tayyor bo'ldingiz.",
        main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cb_setname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _delete_clicked(query)
    await _send(query.message.chat, "Yangi ismingizni kiriting:")
    return ASK_NAME


# =======================================================================
# Bosh menyu
# =======================================================================
async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _next_step(query, "Bosh menyu:", main_menu_keyboard())
    return ConversationHandler.END


# =======================================================================
# Yangi yozuv: mahsulot tanlash
# =======================================================================
async def cb_new_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
    return CHOOSING_CATEGORY


async def cb_choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cat_index = int(query.data.split(":")[1])
    if cat_index < 0 or cat_index >= len(PRODUCT_CATEGORIES):
        await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
        return CHOOSING_CATEGORY

    context.user_data["category_index"] = cat_index
    cat_name = PRODUCT_CATEGORIES[cat_index]["name"]
    items = PRODUCT_CATEGORIES[cat_index]["items"]

    if len(items) == 1:
        context.user_data["variant"] = items[0]
        await _next_step(
            query,
            f"Tanlandi: {short_category_name(cat_name)} — {items[0]}\n\n"
            "Kim chiqargan? (ism kiriting)",
        )
        return ASK_WORKER

    await _next_step(
        query,
        f"«{short_category_name(cat_name)}» — rang/variantni tanlang:",
        variant_keyboard(cat_index, 0),
    )
    return CHOOSING_VARIANT


async def cb_variant_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    cat_index = context.user_data.get("category_index")
    if cat_index is None or cat_index >= len(PRODUCT_CATEGORIES):
        await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
        return CHOOSING_CATEGORY
    try:
        await query.edit_message_reply_markup(reply_markup=variant_keyboard(cat_index, page))
    except TelegramError:
        await _next_step(query, "Rang/variantni tanlang:", variant_keyboard(cat_index, 0))
    return CHOOSING_VARIANT


async def cb_back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
    return CHOOSING_CATEGORY


async def cb_choose_variant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    item_index = int(query.data.split(":")[1])
    cat_index = context.user_data.get("category_index")
    if cat_index is None or cat_index >= len(PRODUCT_CATEGORIES):
        await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
        return CHOOSING_CATEGORY

    items = PRODUCT_CATEGORIES[cat_index]["items"]
    if item_index < 0 or item_index >= len(items):
        await _next_step(query, "Rang/variantni tanlang:", variant_keyboard(cat_index, 0))
        return CHOOSING_VARIANT

    variant = items[item_index]
    context.user_data["variant"] = variant

    await _next_step(
        query,
        f"Tanlandi: {short_category_name(PRODUCT_CATEGORIES[cat_index]['name'])} — {variant}\n\n"
        "Kim chiqargan? (ism kiriting)",
    )
    return ASK_WORKER


async def receive_worker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    worker = (update.message.text or "").strip()
    if not worker:
        await _send(update.effective_chat, "Iltimos, ismni kiriting (masalan: Farxod):")
        return ASK_WORKER
    context.user_data["worker"] = worker
    await _send(update.effective_chat, "Palletda nechta bor? (son kiriting)")
    return ENTERING_QTY


# =======================================================================
# Miqdor va izoh
# =======================================================================
async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip().replace(" ", "").replace(",", ".")
    text = raw.rstrip("кКkK")
    if not text.isdigit() or int(text) <= 0:
        await _send(update.effective_chat, "Iltimos, musbat butun son kiriting (masalan: 48):")
        return ENTERING_QTY
    context.user_data["quantity"] = int(text)
    suggestions = await db.get_frequent_notes(update.effective_user.id, limit=5)
    context.user_data["note_suggestions"] = [row["notes"] for row in suggestions]
    if suggestions:
        await _send(
            update.effective_chat,
            "Izohni tanlang (yoki o'zingiz yozing):",
            notes_suggest_keyboard(context.user_data["note_suggestions"]),
        )
    else:
        await _send(update.effective_chat, "Izohni yozing:")
    return ENTERING_NOTES_TEXT


async def cb_note_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    suggestions = context.user_data.get("note_suggestions") or []
    if idx < 0 or idx >= len(suggestions):
        await _next_step(query, "Izohni yozing:")
        return ENTERING_NOTES_TEXT
    # Xabar o'chiriladi, natija esa YANGI xabar sifatida yuboriladi
    # (o'chirilgan xabarga reply qilish Telegram'da xato beradi).
    await _delete_clicked(query)
    return await _save_and_reply(update, context, notes=suggestions[idx])


async def receive_notes_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    notes = (update.message.text or "").strip()
    if not notes:
        await _send(update.effective_chat, "Izoh bo'sh bo'lmasligi kerak. Izohni yozing:")
        return ENTERING_NOTES_TEXT
    return await _save_and_reply(update, context, notes=notes)


async def _save_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, notes: str) -> int:
    telegram_id = update.effective_user.id
    chat = update.effective_chat

    missing = [key for key in ("category_index", "variant", "quantity") if key not in context.user_data]
    if missing:
        logger.warning("Yozuv uchun kerakli ma'lumot yo'q: %s", missing)
        await _send(chat, "Ma'lumotlar to'liq emas. Qaytadan boshlang.", main_menu_keyboard())
        return ConversationHandler.END

    cat_index = context.user_data["category_index"]
    category = PRODUCT_CATEGORIES[cat_index]["name"]
    variant = context.user_data["variant"]
    quantity = context.user_data["quantity"]
    worker = (
        context.user_data.get("worker")
        or await db.get_worker_name(telegram_id)
        or (update.effective_user.full_name or "Noma'lum")
    )

    try:
        record_id = await db.insert_record(
            telegram_id=telegram_id,
            category=category,
            variant=variant,
            quantity=quantity,
            worker=worker,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Yozuvni saqlashda xatolik: %r", exc)
        await _send(
            chat,
            "Ma'lumotlar bazasi bilan bog'lanishda xatolik. Iltimos, birozdan keyin qayta urinib ko'ring.",
            main_menu_keyboard(),
        )
        return ConversationHandler.END

    text = (
        "✅ Saqlandi!\n\n"
        f"Mahsulot: {short_category_name(category)}\n"
        f"Rang: {variant}\n"
        f"Soni: {quantity}\n"
        f"Kim chiqargan: {worker}"
    )
    if notes:
        text += f"\nIzoh: {notes}"

    if update.callback_query is not None:
        await _delete_clicked(update.callback_query)
    await _send(chat, text, after_save_keyboard(record_id))
    return ConversationHandler.END


async def cb_quick_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xuddi shu mahsulotdan yana bitta pallet qo'shish — faqat sonni qayta so'raydi."""
    query = update.callback_query
    await query.answer()
    if "category_index" not in context.user_data or "variant" not in context.user_data:
        await _next_step(query, "Mahsulot turini tanlang:", category_keyboard())
        return CHOOSING_CATEGORY
    await _next_step(query, "Palletda nechta bor? (son kiriting)")
    return ENTERING_QTY


# =======================================================================
# Bekor qilish
# =======================================================================
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _send(update.effective_chat, "Bekor qilindi.", main_menu_keyboard())
    return ConversationHandler.END


# =======================================================================
# Bitta yozuv uchun PDF (saqlangandan keyingi tugma)
# =======================================================================
async def cb_pdf_single(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda...")
    chat = query.message.chat
    record_id = int(query.data.split(":")[1])
    try:
        rows = await db.get_records_by_ids([record_id])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Yozuvni olishda xatolik: %r", exc)
        await _delete_clicked(query)
        await _send(chat, "Ma'lumotlar bazasi bilan bog'lanishda xatolik.")
        return

    if not rows:
        await _delete_clicked(query)
        await _send(chat, "Yozuv topilmadi.")
        return

    record = rows[0]
    # «Yana shu mahsulotdan qo'shish» bilan to'plangan ayni partiyaning barcha
    # palletlari bitta PDF ichida chiqadi.
    try:
        batch = await db.get_batch_records(
            update.effective_user.id,
            record["category"],
            record["variant"],
            record["worker"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Partiyani olishda xatolik: %r", exc)
        batch = [record]

    if len(batch) == 1:
        pdf_bytes = build_record_pdf(batch[0])
        filename = f"pallet_{batch[0]['id']}.pdf"
        caption = "Pallet hujjati"
    else:
        pdf_bytes = build_pallet_pages_pdf(list(batch))
        total_qty = sum(r["quantity"] for r in batch)
        filename = f"palletlar_{batch[0]['id']}_{batch[-1]['id']}.pdf"
        caption = f"Partiya palletlari ({len(batch)} ta, jami {total_qty} K)"

    await _delete_clicked(query)
    await _send_document(chat, pdf_bytes, filename, caption)


# =======================================================================
# Bugungi yozuvlar
# =======================================================================
async def cb_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    try:
        records = await db.get_today_records(telegram_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bugungi yozuvlarni olishda xatolik: %r", exc)
        await _next_step(query, "Ma'lumotlar bazasi bilan bog'lanishda xatolik.", main_menu_keyboard())
        return

    if not records:
        await _next_step(query, "Bugun hali yozuv yo'q.", main_menu_keyboard())
        return

    total_qty = sum(r["quantity"] for r in records)
    lines = [f"📋 Bugungi yozuvlar ({len(records)} ta, jami {total_qty} K):\n"]
    for i, r in enumerate(records, start=1):
        when = parse_dt(r["date"])
        lines.append(
            f"{i}. {short_category_name(r['category'])} — {r['variant']} — "
            f"{r['quantity']} K ({when.strftime('%H:%M')})"
        )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖨 Hammasini PDF (bitta faylda)", callback_data="menu:today_pdf")],
            [InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu:main")],
        ]
    )

    # Telegram xabari 4096 belgidan oshmasligi kerak — kerak bo'lsa bo'laklarga ajratamiz.
    chunks = _split_text("\n".join(lines))
    await _next_step(query, chunks[0], kb)
    for extra in chunks[1:]:
        await _send(update.effective_chat, extra)


async def cb_today_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda...")
    chat = query.message.chat
    telegram_id = update.effective_user.id
    try:
        records = await db.get_today_records(telegram_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bugungi yozuvlarni olishda xatolik: %r", exc)
        await _delete_clicked(query)
        await _send(chat, "Ma'lumotlar bazasi bilan bog'lanishda xatolik.")
        return

    if not records:
        await _delete_clicked(query)
        await _send(chat, "Bugun hali yozuv yo'q.")
        return

    pdf_bytes = build_pallet_pages_pdf(list(records))
    today_str = now().strftime("%Y%m%d")
    await _delete_clicked(query)
    await _send_document(
        chat,
        pdf_bytes,
        f"bugungi_hujjatlar_{today_str}.pdf",
        f"Bugungi barcha palletlar ({len(records)} ta)",
    )


# =======================================================================
# Eksport (barcha yozuvlar — barcha xodimlar)
# =======================================================================
async def cb_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Excel tayyorlanmoqda...")
    chat = query.message.chat
    try:
        records = await db.get_user_records(update.effective_user.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Yozuvlarni olishda xatolik: %r", exc)
        await _delete_clicked(query)
        await _send(chat, "Ma'lumotlar bazasi bilan bog'lanishda xatolik.")
        return

    if not records:
        await _delete_clicked(query)
        await _send(chat, "Hali yozuv yo'q.")
        return

    excel_bytes = build_excel(list(records))
    stamp = now().strftime("%Y%m%d_%H%M")
    await _delete_clicked(query)
    await _send_document(
        chat,
        excel_bytes,
        f"hisobot_{stamp}.xlsx",
        f"Sizning yozuvlaringiz — jami {len(records)} ta",
    )


async def cb_export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda, biroz kutib turing...")
    chat = query.message.chat
    try:
        records = await db.get_user_records(update.effective_user.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Yozuvlarni olishda xatolik: %r", exc)
        await _delete_clicked(query)
        await _send(chat, "Ma'lumotlar bazasi bilan bog'lanishda xatolik.")
        return

    if not records:
        await _delete_clicked(query)
        await _send(chat, "Hali yozuv yo'q.")
        return

    pdf_bytes = build_pallet_pages_pdf(list(records))
    stamp = now().strftime("%Y%m%d_%H%M")
    await _delete_clicked(query)
    await _send_document(
        chat,
        pdf_bytes,
        f"barcha_palletlar_{stamp}.pdf",
        f"Jami {len(records)} ta pallet, har biri o'z sahifasida",
    )


# =======================================================================
# Xatoliklar
# =======================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, Conflict):
        logger.warning("Telegram Conflict: %s", error)
        return
    if isinstance(error, NetworkError):
        logger.warning("Tarmoq xatosi: %r", error)
        return

    logger.error("Tayyorlanmagan xatolik: %r", error, exc_info=error)

    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "Xatolik yuz berdi. Iltimos, birozdan keyin qayta urinib ko'ring."
            )
        except TelegramError:
            pass


# =======================================================================
# Ilova qurish
# =======================================================================
def build_application(webhook_mode: bool = False) -> Application:
    builder = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        # Telegram API'ga ulanish vaqti kechikkan bo'lsa — timeout beriladi.
        # PTB standart read_timeout = 5 s, bu ba'zi vaqtlarda yetarli emas.
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
    )
    if webhook_mode:
        # Webhook rejimida o'z serverimiz ishlaydi — PTB'ning updater'i kerak emas.
        builder = builder.updater(None)

    app = builder.build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(cb_new_record, pattern="^menu:new$"),
            CallbackQueryHandler(cb_setname, pattern="^menu:setname$"),
            CallbackQueryHandler(cb_quick_add, pattern="^quick_add$"),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(cb_choose_category, pattern=r"^cat:\d+$"),
                CallbackQueryHandler(cb_main_menu, pattern="^menu:main$"),
            ],
            CHOOSING_VARIANT: [
                CallbackQueryHandler(cb_choose_variant, pattern=r"^var:\d+$"),
                CallbackQueryHandler(cb_variant_page, pattern=r"^vpage:\d+$"),
                CallbackQueryHandler(cb_back_to_categories, pattern=r"^back:cat$"),
            ],
            ASK_WORKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_worker)],
            ENTERING_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity)],
            ENTERING_NOTES_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_notes_text),
                CallbackQueryHandler(cb_note_pick, pattern=r"^note_pick:\d+$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CommandHandler("help", cmd_help),
            CallbackQueryHandler(cb_quick_add, pattern="^quick_add$"),
            CallbackQueryHandler(cb_main_menu, pattern="^menu:main$"),
        ],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(conv)

    # Konversatsiyadan tashqari, mustaqil tugmalar
    app.add_handler(CallbackQueryHandler(cb_pdf_single, pattern=r"^pdf:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_today, pattern="^menu:today$"))
    app.add_handler(CallbackQueryHandler(cb_today_pdf, pattern="^menu:today_pdf$"))
    app.add_handler(CallbackQueryHandler(cb_export_excel, pattern="^menu:export_excel$"))
    app.add_handler(CallbackQueryHandler(cb_export_pdf, pattern="^menu:export_pdf$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^menu:main$"))

    app.add_error_handler(error_handler)

    return app


async def _post_init(app: Application) -> None:
    await db.init_db()
    logger.info(
        "Ma'lumotlar bazasi tayyor (%s rejimi).",
        "PostgreSQL" if db.USE_POSTGRES else "SQLite",
    )


async def _post_shutdown(app: Application) -> None:
    await db.close_db()


# =======================================================================
# Keep-alive (Render free tier uxlamasligi uchun)
# =======================================================================
_keepalive_task: asyncio.Task | None = None


async def _keepalive_loop(url: str) -> None:
    while True:
        await asyncio.sleep(config.KEEPALIVE_INTERVAL)
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    logger.info("Keep-alive %s -> HTTP %s", url, resp.status)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Keep-alive xatosi (%s): %r", url, exc)


# =======================================================================
# Rejimlar
# =======================================================================
def _setup_event_loop() -> asyncio.AbstractEventLoop:
    """Python 3.14 da `asyncio.get_event_loop()` joriy loop yo'q bo'lsa
    RuntimeError beradi — loop'ni aniq yaratamiz (PTB 21.6 ham shuni talab qiladi)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("event loop yopilgan")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _webhook_secret() -> str:
    """Telegram webhook `secret_token` uchun xavfsiz qiymat.

    Telegram secret_token faqat `A-Z a-z 0-9 _ -` belgilarini qabul qiladi —
    bot tokenidagi `:` belgisi rad etiladi. Shuning uchun tokenimizdan
    SHA-256 xesh hosil qilinadi. `WEBHOOK_SECRET` env o'zgaruvchisi orqali
    boshqa qiymat ham berilishi mumkin.
    """
    if config.WEBHOOK_SECRET:
        return config.WEBHOOK_SECRET
    return hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode("utf-8")).hexdigest()


async def _set_webhook_with_retry(
    app: Application, webhook_url: str, secret: str, attempts: int = 3
) -> bool:
    """Webhook'ni o'rnatadi (Telegram vaqtincha javob bermasa — qayta urinadi).

    Qaytaradi: `True` — webhook o'rnatildi, `False` — urinishlar tugadi.
    """
    for attempt in range(1, attempts + 1):
        try:
            await app.bot.set_webhook(
                url=webhook_url,
                secret_token=secret,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
            )
            logger.info("Webhook o'rnatildi: %s", webhook_url)
            return True
        except (TelegramError, OSError) as exc:
            logger.warning(
                "Webhook o'rnatilmadi (urinish %s/%s): %r", attempt, attempts, exc
            )
            if attempt < attempts:
                await asyncio.sleep(10)
    return False


async def _webhook_supervisor(
    app: Application, webhook_url: str, secret: str, interval: int = 60
) -> None:
    """Webhook o'rnatilmagan bo'lsa — doimiy ravishda qayta urinish.

    Telegram API vaqtincha ishlamasa, bot o'chib qolmasligi kerak:
    server yana uxlab turadi va keyin webhook qayta o'rnatiladi.
    """
    while True:
        try:
            if await _set_webhook_with_retry(app, webhook_url, secret, attempts=1):
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook supervisor xatosi: %r", exc)
        await asyncio.sleep(interval)


async def _initialize_with_retry(app: Application, attempts: int = 5) -> None:
    """`app.initialize()` + `post_init` — tarmoq xatolarida qayta urinadi.

    Telegram API vaqtincha javob bermasa (yoki bazaga ulanish kechiksa),
    bot darhol o'lmaydi — bir necha daqiqa ichida qayta urinadi.
    """
    delay = 5.0
    last_exc: Exception | None = None
    initialized = False
    for attempt in range(1, attempts + 1):
        try:
            if not initialized:
                await app.initialize()
                initialized = True
            if app.post_init:
                await app.post_init(app)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Boshlashda xatolik (urinish %s/%s): %r — %s soniya kutib qayta uriniladi",
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"Botni ishga tushirib bo'lmadi: {last_exc!r}")


async def _run_webhook_mode() -> None:
    """Server rejimi: webhook + HTTP server (/health) + keep-alive."""
    base_url = config.PUBLIC_URL
    port = config.PORT
    secret = _webhook_secret()

    app = build_application(webhook_mode=True)
    server = WebhookServer(
        app,
        secret,
        webhook_path=config.WEBHOOK_PATH,
        host=config.HOST,
        port=port,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop(signame: str) -> None:
        logger.info("%s signali olindi — bot to'xtatilmoqda...", signame)
        stop_event.set()

    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop, signame)
        except (NotImplementedError, RuntimeError):
            # Windows: `add_signal_handler` ishlamaydi — `signal.signal` bilan urinib ko'ramiz.
            try:
                signal.signal(sig, lambda *_: _request_stop(signame))
            except (ValueError, OSError):
                pass

    await _initialize_with_retry(app)
    await server.start()
    await app.start()

    webhook_url = f"{base_url}{config.WEBHOOK_PATH}"
    global _keepalive_task, _webhook_task

    if not await _set_webhook_with_retry(app, webhook_url, secret):
        logger.error(
            "Webhook o'rnatilmadi — fon rejimida qayta urinib turamiz (har 60 soniyada)."
        )
        _webhook_task = asyncio.create_task(
            _webhook_supervisor(app, webhook_url, secret)
        )

    if not config.KEEPALIVE_DISABLED and config.KEEPALIVE_INTERVAL > 0:
        _keepalive_task = asyncio.create_task(_keepalive_loop(f"{base_url}/health"))
        logger.info(
            "Keep-alive ishga tushdi: har %s soniyada %s/health",
            config.KEEPALIVE_INTERVAL,
            base_url,
        )

    try:
        await stop_event.wait()
    finally:
        logger.info("Bot to'xtatilmoqda...")
        for task in (_keepalive_task, _webhook_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        # Webhook'ni o'chirmaymiz: Render xizmat qayta ishga tushsa, Telegram'da
        # webhook saqlanib qoladi va yangiliklar navbatga (pending) tushib qoladi.
        await server.stop()
        if app.running:
            await app.stop()
        if app.post_stop:
            await app.post_stop(app)
        await app.shutdown()
        if app.post_shutdown:
            await app.post_shutdown(app)


async def _check_foreign_webhook(app: Application) -> bool:
    """Telegram'da boshqa manzilda webhook o'rnatilgan bo'lsa — ogohlantirish.

    Qaytaradi: `True` — webhook mavjud va bu misol uni olib ketishi mumkin.
    """
    try:
        info = await app.bot.get_webhook_info()
    except TelegramError as exc:
        logger.warning("Webhook holatini tekshirib bo'lmadi: %r", exc)
        return False

    url = (info.url or "").strip()
    if not url:
        return False

    logger.warning(
        "Telegram'da webhook o'rnatilgan: %s (kutilayotgan yangiliklar: %s)",
        url,
        getattr(info, "pending_update_count", "?"),
    )
    return True

def _run_polling_mode(app: Application) -> None:
    """Lokal rejim: long-poll."""
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
        drop_pending_updates=False,
        bootstrap_retries=5,
    )


def _run_polling_with_retry(loop: asyncio.AbstractEventLoop) -> None:
    """Polling rejimini Conflict/jarayon xatolariga qarshi qayta ishga tushirish bilan."""
    delay = 10
    while True:
        try:
            asyncio.set_event_loop(loop)
            _run_polling_mode(build_application())
            return
        except Conflict as exc:
            logger.warning(
                "Boshqa bir misol shu bot bilan ishlayapti (%s). %s sekunddan keyin qayta uriniladi.",
                exc,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)
        except TelegramError as exc:
            logger.error(
                "Telegram xatosi: %r — %s sekunddan keyin qayta ishga tushiriladi.", exc, delay
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Kutilmagan xatolik — %s sekunddan keyin qayta ishga tushiriladi.", delay
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)


# =======================================================================
# Boshqaruv
# =======================================================================
def _validate_token() -> bool:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN topilmadi!\n"
            "  • Render'da: Environment -> Add Environment Variable -> TELEGRAM_BOT_TOKEN\n"
            "  • Lokalda: .env fayli yoki `set TELEGRAM_BOT_TOKEN=...`"
        )
        return False
    if ":" not in token or len(token.split(":")[0]) < 5:
        logger.error("TELEGRAM_BOT_TOKEN noto'g'ri formatda (123456789:AA...).")
        return False
    return True


def _decide_mode() -> str:
    """'webhook' yoki 'polling' — avtomatik tanlash."""
    if config.FORCE_POLLING:
        logger.info("FORCE_POLLING=1 — polling rejimi tanlandi.")
        return "polling"
    if config.PUBLIC_URL:
        return "webhook"
    logger.warning(
        "Tashqi manzil (WEBHOOK_URL/RENDER_EXTERNAL_URL) topilmadi — polling rejimida "
        "ishga tushiladi. Render'da webhook uchun RENDER_EXTERNAL_URL avtomatik beriladi."
    )
    return "polling"


async def _probe_foreign_webhook() -> bool:
    """Telegram'da webhook o'rnatilgan bo'lsa — `True`."""
    app = build_application()
    try:
        await app.initialize()
        return await _check_foreign_webhook(app)
    finally:
        try:
            await app.shutdown()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    _setup_logging()

    if not _validate_token():
        return 2

    mode = _decide_mode()
    logger.info("Rejim: %s", mode)
    logger.info(
        "Baza: %s | Log: %s",
        "PostgreSQL" if config.DATABASE_URL else f"SQLite ({config.DB_PATH})",
        config.LOG_FILE,
    )

    if mode == "webhook":
        try:
            asyncio.run(_run_webhook_mode())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — to'xtatilmoqda...")
        except Exception:  # noqa: BLE001
            logger.exception("Webhook rejimida xatolik")
            return 1
        return 0

    lock = SingleInstanceLock(config.LOCK_FILE) if config.SINGLE_INSTANCE else None
    if lock is not None and not lock.acquire():
        logger.error(
            "Bu bot allaqachon boshqa jarayonda ishlayapti (Conflict xatosining oldini olish uchun). "
            "Avval joriy misolni to'xtiring."
        )
        return 3

    loop = _setup_event_loop()
    try:
        # Telegram'da server webhook'i o'rnatilgan bo'lsa — lokal misol uni
        # o'chirmasligi kerak (aks holda server yangiliklarni qabul qilmay qoladi).
        try:
            has_webhook = loop.run_until_complete(_probe_foreign_webhook())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Oldindan tekshiruvda xatolik: %r", exc)
            has_webhook = False

        if has_webhook and not config.ALLOW_WEBHOOK_TAKEOVER:
            logger.error(
                "Lokal misol serverdagi webhook'ni o'chirib, yangiliklarni qabul qilishni to'xtatadi. "
                "Davom etish uchun ALLOW_WEBHOOK_TAKEOVER=1 qo'ying (yoki serverdagi xizmatni to'xtating)."
            )
            return 3

        _run_polling_with_retry(loop)
    finally:
        if lock is not None:
            lock.release()
        try:
            if not loop.is_running() and not loop.is_closed():
                loop.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
