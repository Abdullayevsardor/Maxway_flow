"""iiko avtomatik stop-listi: diff mantiqi.

Haqiqiy iiko'ga chiqilmaydi — `main.iiko.get_client()` soxta klient bilan
almashtiriladi. Tekshiriladigan asosiy qoidalar:

  * stopga tushgan taom avtomatik MenuItem sifatida yaratiladi;
  * iiko'dan yo'qolgan pozitsiya stopdan olinadi (resolved);
  * terminal guruh javob bermasa — o'sha filialga TEGILMAYDI (eng xavfli holat);
  * qo'lda kiritilgan eski yozuvlar avtomatik yopilmaydi;
  * filialning birinchi sinxronida telegram jim turadi.
"""
import pytest

from conftest import login
from app import models
import main


TG1 = "tg-branch-1"
TG2 = "tg-branch-2"
ORG = "org-1"

P_BURGER = "11111111-1111-1111-1111-111111111111"
P_FRIES = "22222222-2222-2222-2222-222222222222"
P_COLA = "33333333-3333-3333-3333-333333333333"

NAMES = {P_BURGER: "Бургер из iiko", P_FRIES: "Картофель из iiko",
         P_COLA: "Кола из iiko"}


class FakeClient:
    """iiko klientining o'rnini bosadi. `stops` — {terminalGroupId: {productId: balance}}."""

    def __init__(self, stops):
        self.stops = stops
        self.calls = 0

    def organizations(self):
        return [{"id": ORG, "name": "Maxway"}]

    def terminal_groups(self, org_ids):
        return {ORG: [{"id": TG1, "name": "Филиал 1"}, {"id": TG2, "name": "Филиал 2"}]}

    def stop_lists(self, org_ids):
        self.calls += 1
        return self.stops

    def resolve_names(self, org_ids, product_ids):
        return {p: NAMES[p] for p in product_ids if p in NAMES}


@pytest.fixture
def iiko_env(db, seed, monkeypatch):
    """Ikkala filialni iiko terminal guruhlariga bog'laydi va telegramni o'chiradi."""
    sent = []
    monkeypatch.setattr(main, "_send_async",
                        lambda ids, text, **kw: sent.append((list(ids), text)))
    b1, b2 = seed["b1"], seed["b2"]
    for b, tg in ((b1, TG1), (b2, TG2)):
        b.iiko_terminal_id = tg
        b.iiko_org_id = ORG
        b.iiko_synced_at = None
    # oldingi testlardan qolgan yozuvlar aralashmasin
    db.query(models.StopEntry).delete()
    db.commit()
    yield {"sent": sent, "b1": b1, "b2": b2}
    db.query(models.StopEntry).delete()
    for b in (b1, b2):
        b.iiko_terminal_id = ""
        b.iiko_org_id = ""
        b.iiko_synced_at = None
    db.commit()


def run_sync(db, monkeypatch, stops):
    fake = FakeClient(stops)
    monkeypatch.setattr(main.iiko, "get_client", lambda: fake)
    return main.iiko_sync_once(db)


def active_names(db, branch):
    q = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == branch.id,
        models.StopEntry.resolved == False).all()
    return sorted((e.menu_item.name if e.menu_item else "?") for e in q)


def test_birinchi_sinxron_taom_yaratadi_va_telegram_jim(db, iiko_env, monkeypatch):
    """Stopga tushgan GUID uchun MenuItem avtomatik paydo bo'ladi."""
    res = run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    assert res["ok"] and res["added"] == 1
    assert active_names(db, iiko_env["b1"]) == ["Бургер из iiko"]

    mi = db.query(models.MenuItem).filter(models.MenuItem.ext_id == P_BURGER).one()
    assert mi.name == "Бургер из iiko"
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == iiko_env["b1"].id).one()
    assert e.source == main.SOURCE_IIKO
    assert e.reason == main.REASON_NOT_SET
    assert e.created_by is None
    # birinchi sinxron — kanal jim
    assert iiko_env["sent"] == []


def test_ikkinchi_sinxronda_yangi_stop_telegramga_ketadi(db, iiko_env, monkeypatch):
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    iiko_env["sent"].clear()
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0, P_FRIES: 0.0}, TG2: {}})
    assert active_names(db, iiko_env["b1"]) == ["Бургер из iiko", "Картофель из iiko"]
    assert len(iiko_env["sent"]) == 1
    assert "Картофель из iiko" in iiko_env["sent"][0][1]
    assert "iiko" in iiko_env["sent"][0][1]          # manba ko'rsatilgan


def test_iikodan_yoqolgan_pozitsiya_stopdan_olinadi(db, iiko_env, monkeypatch):
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0, P_FRIES: 0.0}, TG2: {}})
    iiko_env["sent"].clear()
    res = run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    assert res["resolved"] == 1
    assert active_names(db, iiko_env["b1"]) == ["Бургер из iiko"]
    gone = db.query(models.StopEntry).filter(
        models.StopEntry.resolved == True).one()
    assert gone.resolved_at is not None
    assert len(iiko_env["sent"]) == 1
    assert "Снят со стопа" in iiko_env["sent"][0][1]


def test_javob_bermagan_terminal_guruhga_tegilmaydi(db, iiko_env, monkeypatch):
    """Eng xavfli holat: kassa o'chiq bo'lsa iiko o'sha guruhni javobda bermaydi.
    Bunda filialning butun stop-listi noto'g'ri tozalanib ketmasligi kerak."""
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {P_COLA: 0.0}})
    iiko_env["sent"].clear()
    res = run_sync(db, monkeypatch, {TG2: {P_COLA: 0.0}})       # TG1 umuman yo'q
    assert res["offline"] == [iiko_env["b1"].name]
    assert res["resolved"] == 0
    assert active_names(db, iiko_env["b1"]) == ["Бургер из iiko"]
    assert iiko_env["sent"] == []


def test_qolda_kiritilgan_eski_yozuv_avtomatik_yopilmaydi(db, iiko_env, monkeypatch):
    """Eski qo'lda yozuvlar tarixda qoladi — sync ularga tegmaydi."""
    dish = seed_dish(db, "Ручное блюдо")
    e = models.StopEntry(branch_id=iiko_env["b1"].id, menu_item_id=dish.id,
                         reason="wrong_order", source=main.SOURCE_MANUAL,
                         created_at=models.tashkent_now())
    db.add(e)
    db.commit()
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    db.refresh(e)
    assert e.resolved is False
    assert e.source == main.SOURCE_MANUAL


def test_qolda_yozuv_iikoda_chiqsa_dublikat_yaratilmaydi(db, iiko_env, monkeypatch):
    """Bir taom qo'lda ham, iiko'da ham stopda bo'lsa — ikkinchi yozuv yaratilmaydi,
    mavjudi avtomatikaga o'tadi."""
    dish = seed_dish(db, "Бургер из iiko", ext_id=P_BURGER)
    e = models.StopEntry(branch_id=iiko_env["b1"].id, menu_item_id=dish.id,
                         reason="wrong_order", source=main.SOURCE_MANUAL,
                         created_at=models.tashkent_now())
    db.add(e)
    db.commit()
    res = run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    assert res["added"] == 0
    db.refresh(e)
    assert e.source == main.SOURCE_IIKO
    assert e.resolved is False
    assert len(active_names(db, iiko_env["b1"])) == 1


def test_boglanmagan_filialga_tegilmaydi(db, seed, monkeypatch):
    """Terminal guruhi ko'rsatilmagan filial sinxronizatsiyada qatnashmaydi."""
    for b in (seed["b1"], seed["b2"]):
        b.iiko_terminal_id = ""
    db.commit()
    res = run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}})
    assert res["branches"] == 0 and res["added"] == 0


def seed_dish(db, name, ext_id=None):
    mi = models.MenuItem(name=name, ext_id=ext_id, is_active=True)
    db.add(mi)
    db.commit()
    return mi


def test_sabab_aniqlanganda_ikkinchi_xabar_ketadi(db, iiko_env, monkeypatch, client):
    """iiko «не указана» bilan qo'yadi; odam sababni belgilaganda xabar ketadi."""
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == iiko_env["b1"].id).one()
    iiko_env["sent"].clear()

    login(client, seed_admin(db))
    r = client.post(f"/stoplist/{e.id}/edit",
                    data={"reason": "supplier_late", "fields": "reason"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    db.refresh(e)
    assert e.reason == "supplier_late"
    assert len(iiko_env["sent"]) == 1
    assert "Причина стопа уточнена" in iiko_env["sent"][0][1]
    assert "Поставщик опоздал" in iiko_env["sent"][0][1]


def test_sabab_qayta_ozgarsa_xabar_takrorlanmaydi(db, iiko_env, monkeypatch, client):
    """Xabar faqat «не указана» → aniq sabab o'tishida ketadi, keyingi
    tahrirlashlarda kanal shovqin qilmaydi."""
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == iiko_env["b1"].id).one()
    login(client, seed_admin(db))
    client.post(f"/stoplist/{e.id}/edit",
                data={"reason": "supplier_late", "fields": "reason"},
                follow_redirects=False)
    iiko_env["sent"].clear()
    client.post(f"/stoplist/{e.id}/edit",
                data={"reason": "wrong_order", "fields": "reason"},
                follow_redirects=False)
    db.refresh(e)
    assert e.reason == "wrong_order"
    assert iiko_env["sent"] == []


def seed_admin(db):
    return db.query(models.User).filter(
        models.User.role == models.Role.admin).first()


def test_iiko_yozuvini_qolda_stopdan_olib_bolmaydi(db, iiko_env, monkeypatch, client):
    """iiko boshqaradigan yozuv qo'lda olinmaydi — 2 daqiqadan keyin qaytardi."""
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == iiko_env["b1"].id).one()
    login(client, seed_admin(db))
    r = client.post(f"/stoplist/{e.id}/resolve", follow_redirects=False)
    assert r.status_code == 403
    db.refresh(e)
    assert e.resolved is False


def test_iiko_yozuvi_ommaviy_yechimda_ham_himoyalangan(db, iiko_env, monkeypatch, client):
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == iiko_env["b1"].id).one()
    login(client, seed_admin(db))
    r = client.post("/stoplist/resolve-bulk", data={"sid": [str(e.id)]},
                    follow_redirects=False)
    assert r.status_code == 403
    db.refresh(e)
    assert e.resolved is False


def test_iiko_filialiga_qolda_qoshib_bolmaydi(db, iiko_env, seed, client):
    """Filial logini o'z filiali iiko'ga bog'langanda qo'lda qo'sha olmaydi."""
    login(client, seed["branch"])          # b1 logini, b1 iiko'ga bog'langan
    dish = db.query(models.MenuItem).first()
    r = client.post("/stoplist/add",
                    data={"menu_item_id": [str(dish.id)], "reason": "wrong_order"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "iiko" in r.headers["location"]
    r2 = client.get("/stoplist/new", follow_redirects=False)
    assert r2.status_code in (302, 303) and "/stoplist?err=" in r2.headers["location"]


def test_boglanmagan_filial_qolda_qoshishda_davom_etadi(db, iiko_env, seed, client):
    """b2 ni iiko'dan uzsak — o'sha filial logini qo'lda qo'shishni yo'qotmaydi."""
    seed["b2"].iiko_terminal_id = ""
    db.commit()
    login(client, seed["branch2"])
    dish = models.MenuItem(name="Ручной ввод тест", is_active=True)
    db.add(dish)
    db.commit()
    r = client.post("/stoplist/add",
                    data={"menu_item_id": [str(dish.id)], "reason": "wrong_order"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "err=" not in r.headers["location"]
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == seed["b2"].id,
        models.StopEntry.menu_item_id == dish.id).one()
    assert e.source == main.SOURCE_MANUAL
