# Mahsulot Bot — Ishlab chiqarish hisoboti Telegram boti

## Nima uchu naturqadir
Bu bot ishlab chiqarish korxonasida **tayyor mahsulotlarni (palletlarni) qayd qilish** uchun yozilgan Telegram bot. Ishchi bot orqali:
- mahsulot turini (kategoriya) va rang/variantni tanlaydi,
- palletdagi sonini kiritadi,
- ixtiyoriy izoh yozadi,
- natijada barchasi SQLite bazasiga saqlanadi.

Har bir yozuv uchun **oq-qora printerga mos katta harfli A5 PDF hujjat** chiqariladi (palletga yopishtiriladi). Yana kunning barcha palletlari bitta PDF faylga (har biri o'z sahifasida) yoki Excel (.xlsx) hisobotga yuklab olinadi.

---

## Texnologiyalar va versiyalar (EXACT)
| Komponent | Versiya/Joylashuvi |
|---|---|
| Python | 3.14.8 (manzil: `C:\Python314\python.exe`) |
| python-telegram-bot | 21.6 |
| aiohttp | 3.14.3 (webhook uchun) |
| fpdf2 | 2.7.9 (PDF yaratish) |
| openpyxl | 3.1.5 (Excel yaratish) |
| git | 2.55.0.windows.2 |
| Ma'lumotlar bazasi | SQLite (fayl: `mahsulot_bot.db`) |
| Mulohaza hajmi | A5 portret (148x210 mm) |

`requirements.txt` mazmuni:
```
python-telegram-bot==21.6
aiohttp==3.14.3
fpdf2==2.7.9
openpyxl==3.1.5
```

Diqqat: Python PATH da emas — har doim to'liq manzil bilan ishga tushiriladi yoki `start_bot.bat` orqali.

---

## Papka tuzilishi (har bir fayl)
```
mahsulot_bot/
├── bot.py                      # Asosiy dastur: barcha handlerlar, konversatsiya, webhook/polling
├── config.py                   # Token va DB manzili (token ENV dan olinadi)
├── requirements.txt            # Bog'liqliklar (to'liq versiyalar bilan)
├── start_bot.bat               # Lokal ishga tushirish skripti (token shu yerda — gitignore qilingan)
├── .gitignore                  # __pycache__/, *.pyc, *.db, *.log, start_bot.bat, .env
├── README.md                   # Ushbu hujjat
├── mahsulot_bot.db             # SQLite bazasi (DATA — git'ga qo'yilmaydi)
├── data/
│   ├── __init__.py             # Bo'sh paket-fayl
│   └── products_data.py        # Mahsulotlar ro'yxati (Shablon.xlsx dan olingan)
├── fonts/
│   ├── DejaVuSans.ttf          # Oddiy shrift (Cyrillic qo'llab-quvvatlaydi)
│   └── DejaVuSans-Bold.ttf     # Qalin shrift
├── services/
│   ├── __init__.py
│   ├── db.py                   # SQLite bilan ishlash (init, insert, select, delete)
│   ├── excel_service.py        # Excel (.xlsx) generatsiya
│   └── pdf_service.py          # A5 PDF generatsiya
└── utils/
    ├── __init__.py
    └── product_name_utils.py   # Mol nomini qisqartirish (short_category_name)
```

`__pycache__/` papkalari — (.pyc) — avtomatik yaratiladi, git'ga kirmaydi.
`bot_stdout.log` / `bot_stderr.log` — ishga tushirilganda yaratiladigan loglar (gitignore).
`fonts/` C:\Windows\Fonts dagi DejaVu shriftlaridan ko'chirilgan — PDF da rus Kirill belgilari to'g'ri chiqishi uchun kerak.

---

## O'rnatish va ishga tushirish (lokal)
1. Bog'liqliklarni o'rnatish:
```
C:\Python314\python.exe -m pip install -r requirements.txt
```
2. Token bilan ishga tushirish (2 usul):
   - Ikki marta `start_bot.bat` ni bosish (token skriptda).
   - Yoki PowerShell/Prompt da:
     ```
     set TELEGRAM_BOT_TOKEN=<BOTFATHER_TOKEN>
      C:\Python314\python.exe bot.py
     ```
3. Bot telefonda ishlaydi (polling rejimida — Telegram serveriga hech qanday port ochish shart emas).

### Muhim qoida
Bir vaqtning o'zida **faqat BIRTA** bot jarayoni ishlashi mumkin. Ikkita ishga tushsa, ikkinchisi `telegram.error.Conflict: terminated by other getUpdates request` xatosini beradi. Yangi kod qo'llanilishi uchun botni qayta ishga tushirish (eski jarayonni yopish) shart — Python import'i dastur ishga tushganda bajariladi.

### To'xtatish / qayta ishga tushirish
- Jarayonlarni ko'rish: `Get-Process python* | Select Id, StartTime`
- To'xtatish: `Stop-Process -Id <PID> -Force`
- Qayta ishga tushirish: `start_bot.bat`

---

## Xavfsizlik — token modeli
- Token **hech qachon git repoga yozilmaydi**. `config.py` uni faqat muhit o'zgaruvchisidan o'qiydi:
  ```python
  TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
  ```
  (env o'rnatilmagan bo'lsa `KeyError` chiqadi — token qo'rmasdan bot ishga tushmasi mumkin emasligini kafolatlaydi.)
- Lokal: token `start_bot.bat` da — va bu fayl `.gitignore` ga kiritilgan.
- GitHub (Render) uchun: token Render sozlamalarida env var sifatida o'rnatiladi.
- Hozirgi token README'da saqlanmaydi (faqat o'rnini bosib qo'yish uchun). U BotFather'dan olingan bo'lishi kerak; sirni saqlash kerak bo'lsa — BotFather dan qayta generatsiya qilinishi mumkin.

`.gitignore` mazmuni:
```
__pycache__/
*.pyc
*.db
*.log
start_bot.bat
.env
```

---

## Ma'lumotlar bazasi (SQLite) — sxema
`db.init_db()` bot boshlanganda ikkita jadval yaratadi:

### `workers`
| ustun | tip | izoh |
|---|---|---|
| telegram_id | INTEGER PRIMARY KEY | Telegram foydalanuvchi ID |
| name | TEXT | ism ("Kim chiqargan" bo'ylab saqlanadi) |

### `records`
| ustun | tip | izoh |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | yozuv ID |
| telegram_id | INTEGER | kim qo'shgan |
| category | TEXT | mahsulot to'liq nomi (masalan `Стойкая крем-краска 3Д пакет *18`) |
| variant | TEXT | rang/variant (masalan `7,0 Русый`) |
| quantity | INTEGER | palletdagi soni |
| date | TEXT | ISO format `2026-09-15T08:58:08.123456` (lokal vaqt) |
| worker | TEXT | ism (qo'l bilan kiritiladi, kerak bo'lsa xodim saqlangan nomidan farqli) |
| notes | TEXT NOT NULL DEFAULT '' | izoh |

Sana `date.today().isoformat()` bilan kunning boshlanishiga solishtiriladi (`date LIKE '2026-09-15%'`).

### db.py dagi funksiyalar
- `init_db()` — jadvallar yaratish
- `get_worker_name(telegram_id)` / `set_worker_name(telegram_id, name)` — xodim ismini olish/saqlash (isnati `INSERT ... ON CONFLICT DO UPDATE`)
- `insert_record(telegram_id, category, variant, quantity, worker, notes="", when=None)` → yangi yozuv ID
- `get_records_by_ids(ids)` → berilgan ID lar bo'yicha yozuvlar (bitta PDF uchun)
- `get_today_records(telegram_id)` → faqat bugungi, yangilikni birinchi (id DESC)
- `get_all_records(limit=2000)` → hammasi
- `get_user_records(telegram_id, limit=2000)` → faqat shu foydalanuvchining yozuvlari (eksport uchun)
- `get_batch_records(telegram_id, category, variant, worker)` → bir partiya: shu mahsulot+rang+ishchining o'sha kundagi barcha palletlari («Yana qo'shish» bilan to'planganlar bitta PDF'da chiqishi uchun)
- `get_frequent_notes(telegram_id, limit=5)` → eng ko'p yozilgan izohlar (taklif tugmalari uchun), sotib: ishlatish soni kamayish tartibida, teng bo'lsa — oxirgi ishlatilgan
- `get_records_by_worker_today(telegram_id)` → `get_today_records` aliasi
- `delete_record(record_id)` → o'chirish

Baza `config.DB_PATH` — project papkasidagi `mahsulot_bot.db`. Render'da fayl sistemasi vaqtinchalik (har deploy da tozalanadi) — doimiy saqlash uchun albatta tashqi DB (masalan Neon/Postgres) ga o'tkazish tavsiya etiladi.

---

## Suhbat ssenariysi (konversatsiya holatlari)
6 holat — `(ASK_NAME, CHOOSING_CATEGORY, CHOOSING_VARIANT, ASK_WORKER, ENTERING_QTY, ENTERING_NOTES_TEXT) = range(6)`.

Oqim:
1. `/start` — ism saqlanmagan bo'lsa → `ASK_NAME` (ismni so'raydi, `workers` ga saqlaydi). Saqlangan bo'lsa — darhol bosh menyu.
2. «➕ Yangi yozuv» → `CHOOSING_CATEGORY` — kategoriya ro'yxati (max 1 qatorda bitta tugma).
3. Kategoriya tanlandi:
   - Agar kategoriyada **bitta** item bo'lsa → variant avtomatik o'rnatiladi, `ASK_WORKER` (yangi: SUPER BLOND/ULTRA BLOND/Экстра uchun qulay).
   - Aks holda → `CHOOSING_VARIANT` — rang/variantlar. **8 tadan** sahifalanadi; `⬅️ Oldingi` / `Keyingi ➡️` va `⬅️ Kategoriyalar` tugmalari.
4. Variant tanlandi → `ASK_WORKER` — "Kim chiqargan? (ism kiriting)" — erkin matn.
5. Ism kiritildi → `ENTERING_QTY` — "Palletda nechta bor?" — musbat butun son talab qilinadi.
6. Miqdor kiritildi → `ENTERING_NOTES_TEXT` — **"Izohni tanlang (yoki o'zingiz yozing):"** — foydalanuvchining eng ko'p yozgan 5 ta izohi tugma sifatida taklif qilinadi (`note_pick`). Izoh **MAJBURIY** — bo'sh qoldirilsa yana so'raladi.
7. Izoh tanlandi yoki yozildi → saqlanadi, «✅ Saqlandi!» xabari + quyidagi tugmalar: `🖨 Ushbu pallet uchun PDF`, `➕ Yana shu mahsulotdan qo'shish`, `🆕 Boshqa mahsulot`, `🏠 Bosh menyu`.

Barcha callback tugmalari to'liq ro'yxati:
| callback | vazifa |
|---|---|
| `menu:new` | yangi yozuv — kategoriyalar |
| `menu:today` | bugungi yozuvlarim ro'yxati |
| `menu:today_pdf` | bugungi yozuvlar → bitta PDF fayl |
| `menu:export_excel` | hammasi → Excel (faqat o'z yozuvlari) |
| `menu:export_pdf` | hammasi → PDF (faqat o'z yozuvlari) |
| `menu:setname` | ismni o'zgartirish |
| `menu:main` | bosh menyu |
| `cat:<index>` | kategoriyani tanlash (index `data.products_data` dan) |
| `var:<index>` | variantni tanlash (sahifadagi ID — global, sahifaga bog'liq emas) |
| `vpage:<page>` | variantlar sahifasini almashtirish |
| `back:cat` | variantlar → kategoriyalar |
| `pdf:<record_id>` | bitta yozuv PDF — lekin shu partiya (mahsulot+rang+ishchi, shu kun) bo'yicha barcha yozuvlar bitta PDF ichida chiqadi |
| `note_pick:<index>` | eng ko'p yozilgan izohlardan birini tanlab, to'g'ridan-to'g'ri saqlash |
| `quick_add` | xuddi shu mahsulotdan yana — faqat son so'raydi |
| `menu:main` | bosh menyu |

UX muhim detali: har bir tugma bosilgach, ushbu tugma/xabar o'chiriladi (`_delete_clicked` + `_next_step` → yangi xabar yuboriladi). Kechiklangan xabarlar o'rniga vizual toza oqim hosil bo'ladi.

Fallbacklar: `/cancel`, `/start`, `quick_add`, `menu:main` — istalgan joyda ishlaydi (`allow_reentry=True`).

---

## Mahsulotlar ro'yxati (`data/products_data.py`)
Shablon.xlsx dan avtomatik uziр olingan (aslida qo'lda ko'chirilgan). `PRODUCT_CATEGORIES` — 12 ta kategoriya, har biri `{'name': …, 'items': […]}`:

| # | Kategoriya (to'liq nomi) | Items soni |
|---|---|---|
| 1 | Стойкая крем-краска 3Д пакет *18 | 30 |
| 2 | Элетт кош краска *30 | 2 |
| 3 | BRIO 75ml Для бритьва *24 | 3 |
| 4 | BRIO 50ml После бритьва *24 | 3 |
| 5 | Краска для волос "ECLAIR" *24 OMEGA | 40 (avvalgi 43 — 3 tasi ayraja bersildi) |
| 6 | SUPER BLOND *30 | 1 (o'zi o'zi — bitta toifadagi bir standard variant) |
| 7 | ULTRA BLOND *20 | 1 |
| 8 | Экстра Lock On 100мл | 1 |
| 9 | Стойкая крем-краска 3Д Туба*18 | 30 |
| 10 | Депилятор 0,75 ml. *30 | 2 |
| 11 | Депилятор 125 ml. *20 | 2 |
| 12 | Краска шампун 25 ml. *180 | 3 |

ESLATMA: 6–8 kategoriyalar oldin ECLAIR ichida edi (`"SUPER BLOND" *30`, `ULTRA BLOND *20`, `Экстра Lock On 100мл`). Foydalanuvchi talabi bilan alohida kategoriyalarga ajratildi. ECLAIR'da `"` tirnoq belgisi bor edi — u ham tozalandi.

Bir xil to'plamdan ikkita muhim kategoriya bor: «3Д пакет» (1) va «Туба*18» (9) — bir xil rang ro'yxati, faqat qadoq turi farq qiladi.

Yangi mahsulot qo'shish: `PRODUCT_CATEGORIES` ga oddiy dict qo'shing va `vbos`(variantlar) 8 tadan sahifalanadi — kerakli sahifada ko'rinadi.

---

## PDF generatsiya (`services/pdf_service.py`)
- Shrill: **DejaVu Sans** / DejaVu Sans Bold (`fonts/`). Rus/Cyrillic to'liq qo'llab-quvvatlanadi.
- O'lcham: **A5 portret** (148x210 mm), hujjat chetlari (margin) = **6 mm** — kichik ekan, chop etishda ham katta shrift hajmi bilan katta chiqadi.
- Sahifa tuzilishi (yuqoridan pastga):
  1. **Kategoriya** — qalin 22 pt, ko'p qatordan (to'liq nom qisqartiriladi).
  2. **Rang/variant** — qalin 30 pt.
  3. Yonma-yon 2 ta kichik quti: **Sana** (%d.%m.%Y) va **Kim chiqargan** — 16 mm balandlikda, label 8 pt kulrang, qiymat 15 pt.
  4. **Izoh** — Sana/Ism dan SONI qutigacha bo'lgan butun joyni egallaydi. Matn label ostidan (vertikal markazlashsiz) boshlanadi. Avtofit: shrift 10–32 pt oralig'ida qatorlar soniga qarab kichraytiriladi — qatorlar soni aynan fpdf'ning o'zi (`multi_cell(dry_run=True)` bilan, Bold shrift hisobga olinib) sanaladi, shunda matn hech qachon katakdan chiqmaydi.
  5. **SONI qutisi** — sahifa eng pastida (30 mm balandlikda), `SONI` labeli tepada, jildan 38 pt qalin markazda `NN K`.
- `build_record_pdf(record)` — bitta sahifa.
- `build_pallet_pages_pdf(records)` — ko'p sahifa; ko'p sahifa bo'lsa har sahifa yuqorisida `1 / 5` kabi raqam.

---

## Excel generatsiya (`services/excel_service.py`)
- Varrak: `Ishlab chiqarish`.
- Ustunlar: `№`, `Mahsulot turi`, `Rang / Variant`, `Pallet soni`, `Sana`, `Kim chiqargan`, `Izoh`.
- Sana `dd.mm.yyyy HH:MM` formatida. Birinchi qator qalin (bold).
- Ustun kengliklari: 5, 38, 30, 12, 18, 20, 24.
- `build_excel(records)` → bytes (BytesIO).

---

## Nom qisqartirish (`utils/product_name_utils.py`)
`short_category_name(category)`:
1. `_STRIP_PREFIXES` da boshlanadigan `<prefix>` ni kesib tashlaydi (hozing «Стойкая крем-краска»);
2. Oxiridagi `*<son>` qismini tashlaydi (`_TRAILING_PACK_RE = \s*\*\s*\d+(\.\d+)?\s*$`).

Bazaga/Excelga **to'liq nom** saqlanadi; Telegram tugmalarida va PDF da qisqa ko'rinadi. Misol: `Стойкая крем-краска 3Д пакет *18` → `3Д пакет`.

---

## Webhook rejimi (Render'ga deploy uchun)
Bot 2 rejimda ishlashga tayyor:

### Polling (lokal, standart)
`WEBHOOK_URL` o'zgarmas bo'lsa → `app.run_polling(allowed_updates=Update.ALL_TYPES)`.

### Webhook (serverda)
`main()`:
```python
webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
if webhook_url:
    port = int(os.environ.get("PORT", "8443"))
    url_path = os.environ.get("WEBHOOK_PATH", "/webhook")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        webhook_url=webhook_url + url_path,
        secret_token=os.environ.get("WEBHOOK_SECRET", TELEGRAM_BOT_TOKEN),
        allowed_updates=Update.ALL_TYPES,
    )
```
- `WEBHOOK_URL` = `https://<servis-nomi>.onrender.com`
- `secret_token` Telegram Webhook SDK tomonidan tekshiriladi (callback ekanligini tasdiqlash uchun).
- aiohttp 3.14.3 — PTB 21.6 webhook serveri uchun talab qilinadi.

### Render deploy qadamlar (kaļibtirilgan)
1. GitHub repoga push (bu bajarilgan).
2. Render.com → New Web Service → repo tanlash.
3. Build: `pip install -r requirements.txt`
4. Start: `python bot.py`
5. Free tier.
6. Env var:
   - `TELEGRAM_BOT_TOKEN=<BOTFATHER_TOKEN>`
   - `WEBHOOK_URL=https://<servis-nomi>.onrender.com`
7. Deploy.

Muhim: webhook rejimida baza Render fayl tizimida — **har deploy da tozalanadi**. Yozuvlar uzoq muddat saqlanishi uchun Postgres/Neon migratsiya qilish tavsiya. Bunday holda `insert_record` dan keyin yaqqol ko'rinadigan boshqa boshqa serveriga o'tkazish kerak.

---

## Python 3.14 maxsus nuqta
Python 3.14 da `asyncio.get_event_loop()` (PTB 21.6 ichida chaqiriladi) `RuntimeError` beradi — faqat shu uchun `_setup_event_loop()` qo'shilgan:
```python
def _setup_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
```
Funksiy oilamiz `main()` da faqat polling rejimida kerak; u webhook rejimida ham chaqiriladi (zarar qilmaydi).

---

## GitHub
- Repo: `https://github.com/Farxodxon/mahsulot-bot.git` (private)
- Branch: `master`
- Commit'lar:
  - `211b499` (2026-09-11) — Boshlang'ich: suhbat ssenariysi, PDF/Excel eksport, webhook tayyorgarligi, 14 fayl / 949 qator.
  - `81e5d74` — SUPER BLOND, ULTRA BLOND, Экстра Lock On alohida kategoriyalarga; bitta variantli kategoriyalar variant bosqichini skip qiladi.
- Token repoda TOPILMADI (tekshirilgan) — xavfsiz.

Komanda'lar:
```
git status
git add <fayl>
git commit -m "izoh"
git push
```

---

## Konsol / logslash muhim
- Ushbu Windows'da PowerShell konsol kodlash cp1252 — Rus/Cyrillic `print()` chiqarishda `UnicodeEncodeError` berishi mumkin. Debug uchun faylga UTF-8 yozish afzal (masalan `io.open(..., encoding='utf-8')`).
- Bot logları: `logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)` — stderr ga chiqadi. `Start-Process -RedirectStandardError` bilan faylga olinadi.

---

## Bo'lajak takliflar
- Yozuv tahrir/o'chirish interfeysi.
- Tashqi DB (Neon Postgres) — deplоy toza bo'lmasa saqlanish.
- Kategoriya/pодуктlarini bazadan boshqarish (admin).
- Bitta xodimga bir nechta ish kunlarini tanlash.
- PDF da barcode/QR kod.