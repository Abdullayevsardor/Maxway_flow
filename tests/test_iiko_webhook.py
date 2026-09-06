"""iiko webhook qabul qiluvchisi.

Bu kanal access_token talab qilmaydi — iiko o'zi bizga POST qiladi. Shu bosqichda
u faqat XOM hodisani jurnalga yozadi (stop-listga tegmaydi), chunki iiko to'liq
ro'yxat yuboradimi yoki faqat o'zgarishnimi — hali aniq emas.

Asosiy qoidalar:
  * javob DOIM 200 — aks holda iiko manzilga yuborishni butunlay to'xtatadi;
  * token mos kelmasa ham hodisa yo'qolmaydi (authorized=False bilan yoziladi);
  * buzuq JSON ham 200 oladi va sababi bilan saqlanadi.
"""
import json

import pytest

from conftest import login
from app import models
import main


@pytest.fixture(autouse=True)
def clean_log(db):
    db.query(models.IikoWebhookEvent).delete()
    db.commit()
    yield


def _events(db):
    return db.query(models.IikoWebhookEvent).order_by(
        models.IikoWebhookEvent.id).all()


def test_hodisa_jurnalga_tushadi(client, db, monkeypatch):
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    payload = [{"eventType": "StopListUpdate", "organizationId": "org-1",
                "eventInfo": {"terminalGroupId": "tg-1",
                              "items": [{"productId": "p-1", "balance": 0}]}}]
    r = client.post("/iiko/webhook", json=payload,
                    headers={"Authorization": "s3cret"})
    assert r.status_code == 200
    rows = _events(db)
    assert len(rows) == 1
    assert rows[0].event_type == "StopListUpdate"
    assert rows[0].org_id == "org-1"
    assert rows[0].terminal_group_id == "tg-1"
    assert rows[0].authorized is True
    assert json.loads(rows[0].body)["eventInfo"]["items"][0]["productId"] == "p-1"


def test_bearer_prefiksi_ham_qabul_qilinadi(client, db, monkeypatch):
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    r = client.post("/iiko/webhook", json=[{"eventType": "X"}],
                    headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert _events(db)[0].authorized is True


def test_notogri_token_bilan_ham_200_va_yoziladi(client, db, monkeypatch):
    """Hodisa yo'qolmasin: sxemani aniqlash uchun aynan shu payload kerak."""
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    r = client.post("/iiko/webhook", json=[{"eventType": "X"}],
                    headers={"Authorization": "boshqa"})
    assert r.status_code == 200
    rows = _events(db)
    assert len(rows) == 1
    assert rows[0].authorized is False
    assert "token" in rows[0].note


def test_buzuq_json_ham_200(client, db, monkeypatch):
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    r = client.post("/iiko/webhook", content=b"{bu json emas",
                    headers={"Authorization": "s3cret",
                             "Content-Type": "application/json"})
    assert r.status_code == 200
    rows = _events(db)
    assert len(rows) == 1
    assert "JSON emas" in rows[0].note
    assert "bu json emas" in rows[0].body


def test_royxat_bolmasa_bitta_qator(client, db, monkeypatch):
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    r = client.post("/iiko/webhook", json={"eventType": "Solo"},
                    headers={"Authorization": "s3cret"})
    assert r.status_code == 200
    rows = _events(db)
    assert len(rows) == 1 and rows[0].event_type == "Solo"


def test_stop_listga_tegmaydi(client, db, seed, monkeypatch):
    """Bu bosqichda webhook faqat kuzatadi — hech qanday stop yozuvi paydo
    bo'lmasligi kerak."""
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    before = db.query(models.StopEntry).count()
    client.post("/iiko/webhook", json=[{
        "eventType": "StopListUpdate", "organizationId": "org-1",
        "eventInfo": {"terminalGroupId": "tg-1",
                      "items": [{"productId": "p-1", "balance": 0}]}}],
        headers={"Authorization": "s3cret"})
    assert db.query(models.StopEntry).count() == before


def test_jurnal_faqat_adminga(client, db, seed, monkeypatch):
    monkeypatch.setattr(main, "IIKO_WEBHOOK_TOKEN", "s3cret")
    client.post("/iiko/webhook", json=[{"eventType": "StopListUpdate"}],
                headers={"Authorization": "s3cret"})

    c = login(client, seed["branch"])
    assert c.get("/api/iiko/webhook-log").status_code == 403

    c = login(client, seed["admin"])
    r = c.get("/api/iiko/webhook-log")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["events"][0]["type"] == "StopListUpdate"
