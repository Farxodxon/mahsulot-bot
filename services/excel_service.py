"""Barcha (yoki filtrlangan) yozuvlarni Excel (.xlsx) fayl qilib chiqarish."""
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font


def build_excel(records: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ishlab chiqarish"

    headers = ["№", "Mahsulot turi", "Rang / Variant", "Pallet soni", "Sana", "Kim chiqargan", "Izoh"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i, r in enumerate(records, start=1):
        when = datetime.fromisoformat(r["date"])
        ws.append([
            i,
            r["category"],
            r["variant"],
            r["quantity"],
            when.strftime("%d.%m.%Y %H:%M"),
            r["worker"],
            r["notes"] or "",
        ])

    widths = [5, 38, 30, 12, 18, 20, 24]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = w

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
