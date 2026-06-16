@echo off
chcp 65001 >nul
echo ============================================
echo            MAXWAY ishga tushirilmoqda
echo ============================================
echo.

REM Virtual muhit yaratish (agar yo'q bo'lsa)
if not exist venv (
    echo [1/4] Virtual muhit yaratilmoqda...
    python -m venv venv
)

echo [2/4] Kutubxonalar o'rnatilmoqda...
call venv\Scripts\activate
pip install -r requirements.txt --quiet

REM Demo ma'lumot (faqat birinchi marta)
if not exist maxway.db (
    echo [3/4] Demo ma'lumot yuklanmoqda...
    python seed.py
) else (
    echo [3/4] Ma'lumotlar bazasi mavjud, o'tkazib yuborildi.
)

echo [4/4] Server ishga tushmoqda...
echo.
echo  Brauzerda oching:  http://127.0.0.1:8000
echo  Login: asliddin@gmail.com   Parol: 12345678
echo  To'xtatish uchun: Ctrl + C
echo.
uvicorn main:app --reload
pause
