"""Testlar uchun izolyatsiya qilingan baza va foydalanuvchilar.

Loyihaning haqiqiy maxway.db fayliga tegilmaydi — har bir test sessiyasi uchun
vaqtinchalik SQLite fayli yaratiladi (DATABASE_URL orqali).
"""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# main import qilinishidan OLDIN — app.database shu env'ni o'qiydi
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="maxway_test_"), "test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP_DB.replace("\\", "/")
os.environ.setdefault("MAXWAY_SECRET", "test-secret")

from fastapi.testclient import TestClient          # noqa: E402
import main                                        # noqa: E402
from app import models, auth                       # noqa: E402
from app.database import SessionLocal              # noqa: E402


@pytest.fixture(scope="session")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="session")
def seed(db):
    """Filiallar, blyudolar va har bir rol uchun foydalanuvchi."""
    dep_supply = models.Department(name="Снабжение")
    dep_it = models.Department(name="IT")
    db.add_all([dep_supply, dep_it])
    db.flush()

    b1 = models.Branch(name="Ресторан №12")
    b2 = models.Branch(name="Ресторан №7")
    db.add_all([b1, b2])
    db.flush()

    dishes = [models.MenuItem(name=n, is_active=True)
              for n in ("Бургер Классик", "Картофель фри", "Кола 0.5", "Салат Цезарь")]
    db.add_all(dishes)
    db.flush()

    def mk(email, role, **kw):
        u = models.User(full_name=email.split("@")[0], email=email,
                        hashed_password=auth.hash_password("test12345"),
                        role=role, is_active=True, **kw)
        db.add(u)
        return u

    admin = mk("admin@t.uz", models.Role.admin)
    branch = mk("branch12@t.uz", models.Role.client, user_branch_id=b1.id)
    branch2 = mk("branch7@t.uz", models.Role.client, user_branch_id=b2.id)
    supply = mk("supply@t.uz", models.Role.manager, department_id=dep_supply.id)
    viewer = mk("viewer@t.uz", models.Role.viewer)
    db.commit()
    return {"b1": b1, "b2": b2, "dishes": dishes, "admin": admin,
            "branch": branch, "branch2": branch2, "supply": supply, "viewer": viewer,
            "dep_supply": dep_supply}


@pytest.fixture(scope="session")
def client(seed):
    with TestClient(main.app) as c:
        yield c


def login(client, user):
    """Foydalanuvchi nomidan cookie o'rnatadi va TestClient qaytaradi."""
    client.cookies.set(auth.COOKIE_NAME, auth.create_access_token(user.id))
    return client
