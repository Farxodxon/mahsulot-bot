"""
Oq-qora printerga mos, katta harfli PDF hujjatlar yaratish.

Har bir pallet (yozuv) uchun alohida sahifa — bir sahifada faqat bitta
mahsulot turi. Bir nechta yozuv birlashtirilganda ham (masalan bitta
xodimning bir kunlik barcha palletlari) — barchasi bitta PDF faylga
jamlanadi, lekin har biri o'z sahifasida turadi.
"""
import os
from datetime import datetime
from io import BytesIO

from fpdf import FPDF
from fpdf.enums import MethodReturnValue

from utils.product_name_utils import short_category_name

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "DejaVuSans.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")

MARGIN = 6
PAGE_W = 148  # A5 kenglik (mm), portret
PAGE_H = 210  # A5 balandlik (mm), portret


def _new_pdf() -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A5")
    pdf.set_margin(MARGIN)
    pdf.add_font("DejaVu", "", FONT_REGULAR)
    pdf.add_font("DejaVu", "B", FONT_BOLD)
    pdf.set_auto_page_break(auto=False)
    return pdf


def _count_lines(pdf: FPDF, text: str, size: int, width: float, style: str = "B") -> int:
    """fpdf multi_cell qanday bo'lgan bo'lsa, aynan o'sha qatorlar sonini hisoblaydi
    (uzun so'zlar, yangi qatorlar va so'z oralig'ini ham inobatga olib).
    Chizish paytidagi shrift uslubi (odatda Bold) bilan bir xil ishlatilishi shart."""
    pdf.set_font("DejaVu", style, size)
    lines = pdf.multi_cell(
        w=width,
        text=text,
        dry_run=True,
        output=MethodReturnValue.LINES,
    )
    return len(lines)


def _fit_font_size(
    pdf: FPDF,
    text: str,
    width: float,
    available_h: float,
    min_size: int,
    max_size: int,
    style: str = "B",
) -> int:
    for size in range(max_size, min_size - 1, -1):
        lines = _count_lines(pdf, text, size, width, style)
        if lines * size * 0.46 <= available_h:
            return size
    return min_size


def _field_box(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    value_size: int = 15,
    auto_fit: bool = False,
):
    pdf.rect(x, y, w, h)
    pdf.set_xy(x + 3, y + 2)
    pdf.set_text_color(100, 100, 100)
    pdf.set_font("DejaVu", "", 8)
    pdf.cell(w - 6, 4, label)

    value = value if value.strip() else " "
    text_h = 5.5
    start_y = y + 7.5
    if auto_fit:
        value_size = _fit_font_size(pdf, value, w - 6, h - 9.5, 10, value_size)
        text_h = value_size * 0.46
    pdf.set_xy(x + 3, start_y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "B", value_size)
    pdf.multi_cell(w - 6, text_h, value)


def _draw_pallet_page(pdf: FPDF, record, page_label: str | None = None):
    pdf.add_page()
    content_w = PAGE_W - 2 * MARGIN

    y = MARGIN
    if page_label:
        pdf.set_xy(MARGIN, y)
        pdf.set_text_color(110, 110, 110)
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(content_w, 5, page_label, align="R")
        y += 8

    category = short_category_name(record["category"])
    variant = record["variant"]
    quantity = record["quantity"]
    when = datetime.fromisoformat(record["date"])
    worker = record["worker"]
    notes = record["notes"] or ""

    pdf.set_xy(MARGIN, y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "B", 22)
    pdf.multi_cell(content_w, 8.5, category)
    y = pdf.get_y() + 1

    pdf.set_xy(MARGIN, y)
    pdf.set_font("DejaVu", "B", 30)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(content_w, 11, variant)
    y = pdf.get_y() + 7

    # Sana / Kim chiqargan — ikkita katakcha yonma-yon
    box_w = (content_w - 6) / 2
    field_h = 16
    _field_box(pdf, MARGIN, y, box_w, field_h, "Sana", when.strftime("%d.%m.%Y"))
    _field_box(pdf, MARGIN + box_w + 6, y, box_w, field_h, "Kim chiqargan", worker)
    y += field_h + 6

    # Soni — sahifa eng pastida, katta quti
    soni_h = 30
    soni_top = PAGE_H - MARGIN - soni_h

    # Izoh — Sana/Kim chiqargan va Soni orasidagi barcha joyni egallaydi
    gap = 6
    izoh_h = soni_top - gap - y
    _field_box(pdf, MARGIN, y, content_w, izoh_h, "Izoh", notes, value_size=32, auto_fit=True)

    pdf.rect(MARGIN, soni_top, content_w, soni_h)
    pdf.set_xy(MARGIN + 3, soni_top + 2)
    pdf.set_text_color(100, 100, 100)
    pdf.set_font("DejaVu", "", 8)
    pdf.cell(content_w - 6, 4, "SONI")
    pdf.set_xy(MARGIN, soni_top + soni_h / 2 - 10)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "B", 38)
    pdf.cell(content_w, 18, f"{quantity} K", align="C")


def build_record_pdf(record) -> bytes:
    """Bitta yozuv (pallet) uchun bitta sahifalik PDF."""
    pdf = _new_pdf()
    _draw_pallet_page(pdf, record)
    return bytes(pdf.output())


def build_pallet_pages_pdf(records: list) -> bytes:
    """Bir nechta yozuv — bitta faylda, har biri o'z sahifasida."""
    pdf = _new_pdf()
    total = len(records)
    for i, record in enumerate(records, start=1):
        label = f"{i} / {total}" if total > 1 else None
        _draw_pallet_page(pdf, record, page_label=label)
    return bytes(pdf.output())
