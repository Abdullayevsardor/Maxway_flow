"""Parollarni o'zgartirish: python change_pw.py"""
from app.database import SessionLocal
from app import models, auth

db = SessionLocal()
for u in db.query(models.User).all():
    if u.email == "asliddin@gmail.com":
        u.hashed_password = auth.hash_password("1431")
    else:
        u.hashed_password = auth.hash_password("2026")
    print("✅", u.email, "->", "1431" if u.email == "asliddin@gmail.com" else "2026")
db.commit()
db.close()
print("\n🎉 Parollar yangilandi!")
























# special_emails = {
#     "asliddin@gmail.com",
#     "ikkinchi@gmail.com",
#     "uchinchi@gmail.com",
#     "tortinchi@gmail.com",
# }

# if u.email in special_emails:
#     u.hashed_password = auth.hash_password("1431")
# else:
#     u.hashed_password = auth.hash_password("2026")