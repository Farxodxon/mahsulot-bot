"""
Mahsulot nomlarini ekranda va PDF hujjatlarda qisqaroq va kattaroq
ko'rsatish uchun yordamchi funksiya.

Bazada mahsulot to'liq nomi bilan saqlanadi (Excel hisobotda ham to'liq nom
chiqadi), lekin Telegram xabarlarida va PDF hujjatlarda takrorlanib turadigan
uzun qismi va oxiridagi qadoq/sig'im raqami (masalan "*18") olib tashlanadi.
"""
import re

_STRIP_PREFIXES = [
    "Стойкая крем-краска",
]

_TRAILING_PACK_RE = re.compile(r"\s*\*\s*\d+(\.\d+)?\s*$")


def short_category_name(category: str) -> str:
    result = category
    for prefix in _STRIP_PREFIXES:
        if result.startswith(prefix):
            rest = result[len(prefix):].strip()
            if rest:
                result = rest
            break
    result = _TRAILING_PACK_RE.sub("", result).strip()
    return result if result else category
