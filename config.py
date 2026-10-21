"""
Sozlamalar fayli.

TELEGRAM_BOT_TOKEN ni pastga, tirnoqlar ichiga joylashtiring.
BotFather bergan token shu ko'rinishda bo'ladi: 123456789:AAExampleTokenHere

Xavfsizlik uchun bu faylni hech kimga yubormang va ochiq repo (masalan GitHub)ga
qo'ymang.
"""
import os

# Token muhit o'zgaruvchisidan olinadi (start_bot.bat yoki Render'da o'rnatiladi).
# Xavfsizlik uchun token hech qachon git repoga yozilmaydi.
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Ma'lumotlar bazasi fayli qayerda saqlanishi (SQLite rejimi)
DB_PATH = os.path.join(os.path.dirname(__file__), "mahsulot_bot.db")

# PostgreSQL (Neon) ulanish satri. Bo'lsa — Postgres rejimi, bo'lmasa — SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
