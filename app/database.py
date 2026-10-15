"""Ma'lumotlar bazasi ulanishi — Railway (Postgres) yoki local (SQLite).

500+ foydalanuvchи uchun: Postgres'да pool, SQLite'да WAL rejimi.
"""
import importlib.util
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DB_URL = os.environ.get("DATABASE_URL", "").strip()


def _have(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _fix_pg_driver(url: str) -> str:
    """Postgres drayverini HAQIQATAN o'rnatilgan drayverga moslaydi.

    DATABASE_URL «postgresql+psycopg://» (psycopg v3) ko'rinishida kelganda,
    muhitda esa faqat psycopg2-binary bo'lganda ilova start paytida
    «ModuleNotFoundError: No module named 'psycopg'» bilan yiqilardi —
    uvicorn worker'lari ketma-ket o'lib, sayt umuman ko'tarilmasdi. Drayver
    nomi ulanishga ta'sir qilmaydi, shuning uchun uni jim almashtiramiz."""
    head, sep, tail = url.partition("://")
    if not sep or not head.startswith("postgresql"):
        return url
    drv = head.partition("+")[2]
    if drv in ("", "psycopg2") and not _have("psycopg2") and _have("psycopg"):
        head = "postgresql+psycopg"
    elif drv == "psycopg" and not _have("psycopg") and _have("psycopg2"):
        head = "postgresql+psycopg2"
    return head + sep + tail


if DB_URL:
    # Railway/Heroku ba'zан "postgres://" beradi — SQLAlchemy 2.x "postgresql://" kutadi
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
    DB_URL = _fix_pg_driver(DB_URL)
    engine = create_engine(
        DB_URL,
        pool_pre_ping=True,     # uzilган ulanишни tekshiradi
        pool_size=5,
        max_overflow=5,
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
