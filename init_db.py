"""Deploy'дан oldin: jadvallarni yaratish va bo'sh bo'lsa demo ma'lumot.
Ishga tushirish: python init_db.py
"""
from app.database import Base, engine, SessionLocal
from app import models
import seed


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        has_user = db.query(models.User).first()
    finally:
        db.close()
    if not has_user:
        print("Demo ma'lumot yaratilmoqda...")
        seed.seed()
    else:
        print("Baza allaqachon to'ldirilgan — seed o'tkazib yuborildi.")


if __name__ == "__main__":
    main()
