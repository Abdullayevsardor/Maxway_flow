"""Productionда ishga tushirish (Railway): python start.py

Railway Custom Start Command'ни shell'siz ishlatadi, shuning uchun
$PORT va && ishlamaydi. Bu fayl PORT'ни Python ichida o'qiydi.
main.py import bo'lganда baza tayyorlanadi (jadval/ustun + bo'sh bo'lsa seed).
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
    print(f">>> [MAXWAY] start.py: port={port}, workers={workers}", flush=True)
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=workers)