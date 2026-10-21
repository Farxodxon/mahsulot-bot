"""
Vaqt yordamchilari — barcha sanalar korxonaning vaqt zonasi (Asia/Tashkent)
bo'yicha hisoblanadi.

Render serveri UTC'da ishlaydi, lekin ishchilar UTC+5 da yashaydi: agar
`datetime.now()` ishlatilsa, "bugungi yozuvlar" ro'yxati kechqurun 00:00 dan
keyin noto'g'ri kunni ko'rsatadi. Shu sababli barcha vaqtlamalar
`TIMEZONE` (default Asia/Tashkent) orqali olinadi va ISO 8601 ko'rinishida
saqlanadi (`2026-10-21T18:35:12+05:00`).
"""
from datetime import datetime, timedelta, timezone

from config import TIMEZONE

_UTC = timezone.utc
# Fallback: tzdata yo'q bo'lsa (Windows, paket o'rnatilmagan) UTC+5.
_FALLBACK_OFFSET = timedelta(hours=5)


def _get_timezone():
    """Ishlatiladigan vaqt zonasi. `tzdata` paketi o'rnatilmagan bo'lsa
    (Windows) UTC+5 (Toshkent) ga qaytadi."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(TIMEZONE)
    except Exception:
        pass
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("UTC")
    except Exception:
        return timezone(_FALLBACK_OFFSET)


TZ = _get_timezone()


def now() -> datetime:
    """Hozirgi vaqt (belgilangan vaqt zonasi bilan, tz-aware)."""
    return datetime.now(TZ)


def today_str() -> str:
    """Bugungi sana — `YYYY-MM-DD` ko'rinishida (kunlik filtr uchun)."""
    return now().strftime("%Y-%m-%d")


def parse_dt(value: str) -> datetime:
    """Bazadagi ISO satrini `datetime` ga aylantiradi (naive bo'lsa TZ qo'shiladi)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed
