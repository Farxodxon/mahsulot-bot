"""
Ishlab chiqarilgan tayyor mahsulotni qayd qilish uchun Telegram bot.

Ishga tushirish:
    1. requirements.txt dagi paketlarni o'rnating: pip install -r requirements.txt
    2. config.py ichiga BotFather bergan tokenni yozing
    3. python bot.py

Asosiy imkoniyatlar:
    - Mahsulot tanlash (kategoriya -> rang/variant), palletdagi soni, izoh
    - Har bir yozuv uchun katta harfli PDF hujjat (oq-qora printerga mos)
    - Bir kunlik barcha yozuvlarni bitta PDF faylga jamlash (har biri o'z sahifasida)
    - Barcha yozuvlarni Excel (.xlsx) qilib chiqarish
"""
import asyncio
import logging
import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from data.products_data import PRODUCT_CATEGORIES
from services import db
from services.pdf_service import build_record_pdf, build_pallet_pages_pdf
from services.excel_service import build_excel
from utils.product_name_utils import short_category_name

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
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


async def _delete_clicked(query) -> None:
    try:
        await query.message.delete()
    except Exception:
        pass


async def _next_step(query, text: str, reply_markup=None):
    chat = query.message.chat
    await _delete_clicked(query)
    return await chat.send_message(text, reply_markup=reply_markup)


# =======================================================================
# /start va ism so'rash
# =======================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    name = db.get_worker_name(telegram_id)
    if name:
        await update.message.reply_text(
            f"Salom, {name}! Nima qilamiz?", reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Assalomu alaykum! Ishlab chiqarish botiga xush kelibsiz.\n\n"
        "Avval ismingizni kiriting (bu yozuvlarda \"Kim chiqargan\" sifatida ishlatiladi):"
    )
    return ASK_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Iltimos, ismingizni kiriting:")
        return ASK_NAME
    db.set_worker_name(update.effective_user.id, name)
    await update.message.reply_text(
        f"Rahmat, {name}! Endi tayyor bo'ldingiz.", reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def cb_setname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _delete_clicked(query)
    await query.message.reply_text("Yangi ismingizni kiriting:")
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
    cat_index = context.user_data["category_index"]
    await query.edit_message_reply_markup(reply_markup=variant_keyboard(cat_index, page))
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
    cat_index = context.user_data["category_index"]
    variant = PRODUCT_CATEGORIES[cat_index]["items"][item_index]
    context.user_data["variant"] = variant

    await _next_step(
        query,
        f"Tanlandi: {short_category_name(PRODUCT_CATEGORIES[cat_index]['name'])} — {variant}\n\n"
        "Kim chiqargan? (ism kiriting)",
    )
    return ASK_WORKER


async def receive_worker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    worker = update.message.text.strip()
    if not worker:
        await update.message.reply_text("Iltimos, ismni kiriting (masalan: Farxod):")
        return ASK_WORKER
    context.user_data["worker"] = worker
    await update.message.reply_text("Palletda nechta bor? (son kiriting)")
    return ENTERING_QTY


# =======================================================================
# Miqdor va izoh
# =======================================================================
async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(" ", "")
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("Iltimos, musbat butun son kiriting (masalan: 48):")
        return ENTERING_QTY
    context.user_data["quantity"] = int(text)
    suggestions = db.get_frequent_notes(update.effective_user.id, limit=5)
    context.user_data["note_suggestions"] = [row["notes"] for row in suggestions]
    if suggestions:
        await update.message.reply_text(
            "Izohni tanlang (yoki o'zingiz yozing):",
            reply_markup=notes_suggest_keyboard(context.user_data["note_suggestions"]),
        )
    else:
        await update.message.reply_text("Izohni yozing:")
    return ENTERING_NOTES_TEXT


async def cb_note_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    suggestions = context.user_data.get("note_suggestions") or []
    if idx < 0 or idx >= len(suggestions):
        await _next_step(query, "Izohni yozing:")
        return ENTERING_NOTES_TEXT
    await _delete_clicked(query)
    return await _save_and_reply(update, context, notes=suggestions[idx])


async def receive_notes_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    notes = update.message.text.strip()
    if not notes:
        await update.message.reply_text("Izoh bo'sh bo'lmasligi kerak. Izohni yozing:")
        return ENTERING_NOTES_TEXT
    return await _save_and_reply(update, context, notes=notes)


async def _save_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, notes: str) -> int:
    telegram_id = update.effective_user.id
    cat_index = context.user_data["category_index"]
    category = PRODUCT_CATEGORIES[cat_index]["name"]
    variant = context.user_data["variant"]
    quantity = context.user_data["quantity"]
    worker = context.user_data.get("worker") or db.get_worker_name(telegram_id) or update.effective_user.full_name

    record_id = db.insert_record(
        telegram_id=telegram_id,
        category=category,
        variant=variant,
        quantity=quantity,
        worker=worker,
        notes=notes,
    )

    text = (
        "✅ Saqlandi!\n\n"
        f"Mahsulot: {short_category_name(category)}\n"
        f"Rang: {variant}\n"
        f"Soni: {quantity}\n"
        f"Kim chiqargan: {worker}"
    )
    if notes:
        text += f"\nIzoh: {notes}"

    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(text, reply_markup=after_save_keyboard(record_id))
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
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# =======================================================================
# Bitta yozuv uchun PDF (saqlangandan keyingi tugma)
# =======================================================================
async def cb_pdf_single(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda...")
    chat = query.message.chat
    record_id = int(query.data.split(":")[1])
    rows = db.get_records_by_ids([record_id])
    if not rows:
        await _delete_clicked(query)
        await chat.send_message("Yozuv topilmadi.")
        return
    record = rows[0]
    # «Yana shu mahsulotdan qo'shish» bilan to'plangan ayni partiyaning barcha
    # palletlari bitta PDF ichida chiqadi (oxirgi qo'shilgan ham kirmasdan qolmaydi).
    batch = db.get_batch_records(
        update.effective_user.id,
        record["category"],
        record["variant"],
        record["worker"],
    )
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
    await chat.send_document(
        document=pdf_bytes,
        filename=filename,
        caption=caption,
    )


# =======================================================================
# Bugungi yozuvlar
# =======================================================================
async def cb_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    records = db.get_today_records(telegram_id)

    if not records:
        await _next_step(query, "Bugun hali yozuv yo'q.", main_menu_keyboard())
        return

    total_qty = sum(r["quantity"] for r in records)
    lines = [f"📋 Bugungi yozuvlar ({len(records)} ta, jami {total_qty} K):\n"]
    for i, r in enumerate(records, start=1):
        when = datetime.fromisoformat(r["date"])
        lines.append(
            f"{i}. {short_category_name(r['category'])} — {r['variant']} — "
            f"{r['quantity']} K ({when.strftime('%H:%M')})"
        )
    text = "\n".join(lines)

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖨 Hammasini PDF (bitta faylda)", callback_data="menu:today_pdf")],
            [InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu:main")],
        ]
    )
    await _next_step(query, text, kb)


async def cb_today_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda...")
    chat = query.message.chat
    telegram_id = update.effective_user.id
    records = db.get_today_records(telegram_id)
    if not records:
        await _delete_clicked(query)
        await chat.send_message("Bugun hali yozuv yo'q.")
        return
    pdf_bytes = build_pallet_pages_pdf(list(records))
    today_str = datetime.now().strftime("%Y%m%d")
    await _delete_clicked(query)
    await chat.send_document(
        document=pdf_bytes,
        filename=f"bugungi_hujjatlar_{today_str}.pdf",
        caption=f"Bugungi barcha palletlar ({len(records)} ta)",
    )


# =======================================================================
# Eksport (barcha yozuvlar — barcha xodimlar)
# =======================================================================
async def cb_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Excel tayyorlanmoqda...")
    chat = query.message.chat
    records = db.get_user_records(update.effective_user.id)
    if not records:
        await _delete_clicked(query)
        await chat.send_message("Hali yozuv yo'q.")
        return
    excel_bytes = build_excel(list(records))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    await _delete_clicked(query)
    await chat.send_document(
        document=excel_bytes,
        filename=f"hisobot_{stamp}.xlsx",
        caption=f"Sizning yozuvlaringiz — jami {len(records)} ta",
    )


async def cb_export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Hujjat tayyorlanmoqda, biroz kutib turing...")
    chat = query.message.chat
    records = db.get_user_records(update.effective_user.id)
    if not records:
        await _delete_clicked(query)
        await chat.send_message("Hali yozuv yo'q.")
        return
    pdf_bytes = build_pallet_pages_pdf(list(records))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    await _delete_clicked(query)
    await chat.send_document(
        document=pdf_bytes,
        filename=f"barcha_palletlar_{stamp}.pdf",
        caption=f"Jami {len(records)} ta pallet, har biri o'z sahifasida",
    )


# =======================================================================
# Ilova qurish
# =======================================================================
def build_application() -> Application:
    db.init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

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
                CallbackQueryHandler(cb_back_to_categories, pattern="^back:cat$"),
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
            CallbackQueryHandler(cb_quick_add, pattern="^quick_add$"),
            CallbackQueryHandler(cb_main_menu, pattern="^menu:main$"),
        ],
        allow_reentry=True,
    )
    app.add_handler(conv)

    # Konversatsiyadan tashqari, mustaqil tugmalar
    app.add_handler(CallbackQueryHandler(cb_pdf_single, pattern=r"^pdf:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_today, pattern="^menu:today$"))
    app.add_handler(CallbackQueryHandler(cb_today_pdf, pattern="^menu:today_pdf$"))
    app.add_handler(CallbackQueryHandler(cb_export_excel, pattern="^menu:export_excel$"))
    app.add_handler(CallbackQueryHandler(cb_export_pdf, pattern="^menu:export_pdf$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^menu:main$"))

    return app


def _setup_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main():
    app = build_application()
    _setup_event_loop()

    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if webhook_url:
        port = int(os.environ.get("PORT", "8443"))
        url_path = os.environ.get("WEBHOOK_PATH", "/webhook")
        logger.info("Webhook rejimida ishga tushmoqda: %s%s", webhook_url, url_path)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=webhook_url + url_path,
            secret_token=os.environ.get("WEBHOOK_SECRET", TELEGRAM_BOT_TOKEN),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Polling rejimida ishga tushmoqda...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
