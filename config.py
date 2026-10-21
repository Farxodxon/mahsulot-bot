"""
Sozlamalar fayli — bot tokeni, ma'lumotlar bazasi va server parametrlari.

Xavfsizlik: bot tokeni hech qachon git repoga yozilmaydi. U faqat
  1) muhit o'zgaruvchisidan (`TELEGRAM_BOT_TOKEN`), yoki
  2) `mahsulot-bot/.env` faylidan (`.env` `.gitignore` da) olinadi.

Render.com'da `RENDER_EXTERNAL_URL` avtomatik beriladi — shuning uchun
`WEBHOOK_URL` ni qo'lda kiritish shart emas: bot o'zidan o'z webhook
manzilini topadi va `PORT` ga ulanadi (Render buni talab qiladi).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """`.env` faylini o'qib, yo'q bo'lgan muhit o'zgaruvchilarini to'ldiradi."""
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


def _get(*names: str, default: str = "") -> str:
    """Birinchi to'ldirilgan muhit o'zgaruvchisini qaytaradi."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


# --- Bot -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")

# --- Ma'lumotlar bazasi ----------------------------------------------------
# DATABASE_URL bo'lsa — PostgreSQL (Neon), aks holda — SQLite fayli.
DATABASE_URL = _get("DATABASE_URL")
DB_PATH = str(BASE_DIR / "mahsulot_bot.db")
DB_CONNECT_RETRIES = _get_int("DB_CONNECT_RETRIES", 5)
DB_FALLBACK_TO_SQLITE = _get_bool("DB_FALLBACK_TO_SQLITE", True)

# --- Server (webhook) ------------------------------------------------------
# WEBHOOK_URL qo'lda beriladi; bo'lmasa Render'ning RENDER_EXTERNAL_URL'i
# ishlatiladi (Render uni avtomatik qo'yadi).
PUBLIC_URL = _get("WEBHOOK_URL", "RENDER_EXTERNAL_URL").rstrip("/")
WEBHOOK_PATH = _get("WEBHOOK_PATH", default="/webhook")
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = f"/{WEBHOOK_PATH}"
PORT = _get_int("PORT", 10000)
HOST = _get("HOST", default="0.0.0.0")
WEBHOOK_SECRET = _get("WEBHOOK_SECRET")

# --- Vaqt / vaqt zonasi ----------------------------------------------------
# Render serveri UTC'da ishlaydi, korxona esa UTC+5 (Toshkent). Barcha
# "bugungi yozuvlar" hisoblari va hujjatlardagi vaqt shu zonada bo'ladi.
TIMEZONE = _get("TZ", "TIMEZONE", default="Asia/Tashkent")

# --- Boshqalar -------------------------------------------------------------
KEEPALIVE_INTERVAL = _get_int("KEEPALIVE_INTERVAL", 300)
KEEPALIVE_DISABLED = _get_bool("KEEPALIVE_DISABLED")
SINGLE_INSTANCE = _get_bool("SINGLE_INSTANCE", True)
# Telegram'da boshqa webhook o'rnatilgan bo'lsa, lokal pollingni bloklash.
FORCE_POLLING = _get_bool("FORCE_POLLING", False)
# Lokal misol serverdagi webhook'ni o'chirib yuborishga rozilik (ALIAS).
ALLOW_WEBHOOK_TAKEOVER = _get_bool("ALLOW_WEBHOOK_TAKEOVER", False)
# Bitta misol qulfi (Conflict xatosining oldini oladi).
LOCK_FILE = str(BASE_DIR / ".bot.lock")
LOG_LEVEL = _get("LOG_LEVEL", default="INFO").upper()
LOG_FILE = _get("LOG_FILE", default=str(BASE_DIR / "bot.log"))
LOG_TO_FILE = _get_bool("LOG_TO_FILE", True)
IS_RENDER = bool(_get("RENDER")) or bool(_get("RENDER_EXTERNAL_URL"))
