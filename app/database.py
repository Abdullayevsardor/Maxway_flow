"""Ma'lumotlar bazasi ulanishi — Railway (Postgres) yoki local (SQLite).

500+ foydalanuvchи uchun: Postgres'да pool, SQLite'да WAL rejimi.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DB_URL = os.environ.get("DATABASE_URL", "").strip()

if DB_URL:
    # Railway/Heroku ba'zан "postgres://" beradi — SQLAlchemy 2.x "postgresql://" kutadi
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(
        DB_URL,
        pool_pre_ping=True,     # uzilган ulanишни tekshiradi
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
    )
else:
    engine = create_engine(
        "sqlite:///./maxway.db",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    # SQLite'ни ko'p foydalanuvchи uchun bardoshli qilish (WAL + timeout)
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Har bir so'rov uchun DB sessiyasini beradi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
