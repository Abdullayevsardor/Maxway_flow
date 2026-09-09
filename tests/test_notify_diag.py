"""Zayavka telegram xabarlari: tashxis va qayta yuborish.

Sabab: zayavka ochilganda telegram kelmadi, lekin send_telegram hamma xatoni
jim yutardi — nima buzilgani ko'rinmasdi.
"""
import pytest

from conftest import login
from app import models
import main


@pytest.fixture
def tg(monkeypatch):
    """Telegram API'ni to'xtatamiz: haqiqiy xabar ketmasin."""
    calls = []

    def fake(token, method, **params):
        calls.append((method, params))
        if method == "getMe":
            return {"ok": True, "result": {"username": "maxway_bot"}}
        if method == "getChat":
            if params.get("chat_id") == "404":
                return {"ok": False, "description": "chat not found"}
            return {"ok": True, "result": {"first_name": "Тест"}}
        if method == "sendMessage":
            if params.get("chat_id") == "404":
                return {"ok": False, "description": "bot was blocked by the user"}
            return {"ok": True, "result": {}}
        return {"ok": True}

    monkeypatch.setattr(main, "_tg_api", fake)
    monkeypatch.setattr(main, "get_bot_token", lambda: "test-token")
    return calls


def test_tashxis_faqat_adminga(client, seed, tg):
    c = login(client, seed["branch"])
    assert c.get("/api/request-notify-preview").status_code == 403
    c = login(client, seed["admin"])
    assert c.get("/api/request-notify-preview").status_code == 200


def test_tashxis_chatsiz_foydalanuvchini_korsatadi(client, db, seed, tg):
    dep = seed["dep_supply"]
    c = login(client, seed["admin"])
    data = c.get(f"/api/request-notify-preview?department_id={dep.id}").json()
    assert data["bot"] == "@maxway_bot"
    rows = data["categories"][0]["recipients"]
    assert rows, "qabul qiluvchilar topilmadi"
    chatsiz = [r for r in rows if not r.get("chat_id")]
    assert chatsiz, "chat_id yo'q foydalanuvchi belgilanishi kerak"
    assert "chat_id" in chatsiz[0]["error"]


def test_tashxis_yetib_bormaganini_korsatadi(client, db, seed, tg):
    """Bot /start bosilmagan chatga xabar yubora olmaydi — shu ko'rinishi kerak."""
    seed["supply"].telegram_chat_id = "404"
    db.commit()
    try:
        c = login(client, seed["admin"])
        data = c.get(f"/api/request-notify-preview?department_id={seed['dep_supply'].id}").json()
        rows = [r for r in data["categories"][0]["recipients"] if r.get("chat_id") == "404"]
        assert rows and rows[0]["reachable"] is False
        assert rows[0]["error"] == "chat not found"
    finally:
        seed["supply"].telegram_chat_id = None
        db.commit()


def _zayavka(db, seed):
    r = models.Request(title="Тест уведомления", description="",
                       department_id=seed["dep_supply"].id,
                       created_by=seed["branch"].id, branch_id=seed["b1"].id)
    db.add(r)
    db.commit()
    return r


def test_qayta_yuborish_faqat_adminga(client, db, seed, tg):
    r = _zayavka(db, seed)
    c = login(client, seed["branch"])
    assert c.post(f"/requests/{r.id}/notify-again").status_code == 403


def test_qayta_yuborish_ishlaydi(client, db, seed, tg):
    seed["supply"].telegram_chat_id = "555"
    db.commit()
    try:
        r = _zayavka(db, seed)
        oldin = db.query(models.Notification).count()
        c = login(client, seed["admin"])
        resp = c.post(f"/requests/{r.id}/notify-again", follow_redirects=False)
        assert resp.status_code == 302
        yuborilgan = [p for m, p in tg if m == "sendMessage"]
        assert any(p["chat_id"] == "555" for p in yuborilgan)
        assert "Тест уведомления" in yuborilgan[0]["text"]
        # sayt bildirishnomasi takrorlanmasligi kerak — faqat telegram
        assert db.query(models.Notification).count() == oldin
    finally:
        seed["supply"].telegram_chat_id = None
        db.commit()


def test_qayta_yuborishda_xato_korinadi(client, db, seed, tg):
    seed["supply"].telegram_chat_id = "404"
    db.commit()
    try:
        r = _zayavka(db, seed)
        c = login(client, seed["admin"])
        resp = c.post(f"/requests/{r.id}/notify-again", follow_redirects=False)
        joy = resp.headers["location"]
        assert "err=" in joy and "blocked" in joy.replace("%20", " ")
    finally:
        seed["supply"].telegram_chat_id = None
        db.commit()
