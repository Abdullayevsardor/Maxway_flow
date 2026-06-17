# MAXWAY

Ishlarni (zayavkalarni) saqlab boradigan, bo'limlarga ajratadigan va kerakli
ijrochilarga yo'naltiradigan **web + PWA (telefon)** tizimi. Python **FastAPI**'da yozilgan.

## Imkoniyatlar
- 🔐 Login / ro'yxatdan o'tish (rasm dizayniga mos — binafsha login sahifa)
- 📊 Admin dashboard (FixFlow o'rniga **MAXWAY** brendi)
- 🗂️ **10 tagacha bo'lim (otdel)** — har birини bosganda shу bo'lim zayavkalari chiqadi
- 📝 Zayavka yaratish, status (Новые / В работе / Выполнены) va prioritet
- 👤 Ijrochilarni biriktirish (kerakli odamlarga yo'naltirish)
- 📈 Analitika + oylik hisobot
- 📱 PWA — telefonga "ilova" sifatida o'rnatса bo'ladi
- 🔌 JSON API (`/api/...`) — mobil ilova uchun tayyor

## O'rnatish

```bash
# 1. Virtual muhit (ixtiyoriy, lekin tavsiya etiladi)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Kutubxonalar
pip install -r requirements.txt

# 3. Demo ma'lumot (10 bo'lim + admin + namuna zayavkalar)
python seed.py

# 4. Ishga tushirish
uvicorn main:app --reload
```

So'ngra brauzerda oching: **http://127.0.0.1:8000**

## Demo login
| Email | Parol |
|-------|-------|
| `asliddin@gmail.com` | `12345678` |

## Loyiha tuzilishi
```
maxway/
├── main.py              # FastAPI ilova (sahifalar + API)
├── seed.py              # Demo ma'lumot
├── requirements.txt
├── app/
│   ├── database.py      # SQLite ulanish
│   ├── models.py        # User / Department / Request
│   ├── auth.py          # Parol hash + JWT (cookie)
├── templates/           # HTML (Jinja2)
│   ├── login.html  register.html  base.html
│   ├── dashboard.html  requests.html  executors.html  analytics.html
└── static/
    ├── css/style.css    # Dizayn (rasmga mos)
    ├── manifest.json    # PWA
    └── img/             # Ikonkalar
```

## Bo'limni o'zgartirish / qo'shish
`seed.py` faylidagi `DEPARTMENTS` ro'yxatini tahrir qiling (maksimum 10 ta).
Yoki keyinchalik admin paneliga "Bo'lim qo'shish" formasini qo'shib bering.

## Telefon ilovasi sifatida
1. Saytni telefon brauzeriga oching
2. "Add to Home Screen" / "Bosh ekranга qo'shish" tugmasini bosing
3. MAXWAY mustaqil ilova kabi ochiladi (PWA)

> Native iOS/Android ilova kerak bo'lsa — shu API'ni Flutter yoki React Native bilan ulаsh mumkin (`/api/login`, `/api/departments`, `/api/requests`).
