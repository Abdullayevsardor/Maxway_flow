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
    """iiko klientining o'rnini bosadi.

    `stops` — {terminalGroupId: {productId: ma'lumot}}.
    `alive` — kassasi yoqilgan terminal guruhlar; ko'rsatilmasa, javobdagilar
    tirik deb hisoblanadi (haqiqiy iiko'da stopi bor guruh doim javobda bo'ladi).
    `alive_error=True` — is_alive metodi xato beradi (aloqa yo'q holati)."""

    def __init__(self, stops, alive=None, alive_error=False):
        self.stops = stops
        self.alive = set(stops) if alive is None else set(alive)
        self.alive_error = alive_error
        self.calls = 0

    def organizations(self):
        return [{"id": ORG, "name": "Maxway"}]

    def terminal_groups(self, org_ids):
        return {ORG: [{"id": TG1, "name": "Филиал 1"}, {"id": TG2, "name": "Филиал 2"}]}

    def stop_lists(self, org_ids):
        self.calls += 1
        return self.stops

    def alive_terminal_groups(self, org_ids, tg_ids):
        if self.alive_error:
            raise main.iiko.IikoError("is_alive: aloqa yo'q")
        return {t for t in tg_ids if t in self.alive}

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


def run_sync(db, monkeypatch, stops, alive=None, alive_error=False):
    fake = FakeClient(stops, alive=alive, alive_error=alive_error)
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
    # manba haqidagi qator xabarda ko'rsatilmaydi (faqat odam qo'shsa «Добавил»)
    assert "Источник" not in iiko_env["sent"][0][1]
    assert "Добавил" not in iiko_env["sent"][0][1]


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


# ---------- bo'sh stop-list: iiko uni javobda umuman ko'rsatmaydi ----------
# 08.09.2026 da o'lchandi: /api/1/stop_lists javobida FAQAT stopi bor guruhlar
# keladi (45 guruhdan 13 tasi, hammasida stop bor). Shuning uchun «javobda yo'q»
# ni «kassa o'chiq» dan is_alive orqali ajratamiz.

def test_bosh_stoplist_tirik_kassada_tozalanadi(db, iiko_env, monkeypatch):
    """Filialdagi OXIRGI taom stopdan olinsa, guruh javobdan butunlay yo'qoladi.
    Kassa tirik bo'lsa — bu «stop yo'q» degani, yozuv yopilishi kerak."""
    b1 = iiko_env["b1"]
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})
    assert active_names(db, b1) == ["Бургер из iiko"]

    # TG1 endi javobda yo'q, lekin kassasi ishlayapti
    res = run_sync(db, monkeypatch, {TG2: {}}, alive={TG1, TG2})
    assert res["resolved"] == 1
    assert active_names(db, b1) == []
    assert b1.name not in res["offline"]


def test_bosh_stoplist_olik_kassada_tegilmaydi(db, iiko_env, monkeypatch):
    """Xuddi shu holat, lekin kassa o'chiq — holat noma'lum, yozuvga TEGILMAYDI."""
    b1 = iiko_env["b1"]
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})

    res = run_sync(db, monkeypatch, {TG2: {}}, alive={TG2})
    assert res["resolved"] == 0
    assert active_names(db, b1) == ["Бургер из iiko"]
    assert b1.name in res["offline"]


def test_is_alive_xato_bersa_ehtiyotkor_ishlaydi(db, iiko_env, monkeypatch):
    """is_alive javob bermasa — bo'sh ro'yxatlarni tozalamaymiz. Aloqa uzilganda
    butun stop-listni yechib yuborishdan ko'ra, eski holatni saqlagan yaxshi."""
    b1 = iiko_env["b1"]
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0}, TG2: {}})

    res = run_sync(db, monkeypatch, {TG2: {}}, alive_error=True)
    assert res["resolved"] == 0
    assert active_names(db, b1) == ["Бургер из iiko"]


def test_stop_vaqti_iikodan_olinadi(db, iiko_env, monkeypatch):
    """dateAdd — stop kassada qachon qo'yilgani (iiko UTC beradi, +5 Toshkent).
    Sinxron ko'rgan vaqt emas: stopda oylab turgan pozitsiyalar ham bor."""
    from datetime import datetime
    b1 = iiko_env["b1"]
    run_sync(db, monkeypatch, {
        TG1: {P_BURGER: {"balance": 0.0, "sku": "123",
                         "date_add": "2025-11-13 08:44:33.803"}},
        TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == b1.id,
        models.StopEntry.resolved == False).one()
    assert e.created_at == datetime(2025, 11, 13, 13, 44, 33)      # UTC + 5 soat


def test_dateadd_yoq_bolsa_hozirgi_vaqt(db, iiko_env, monkeypatch):
    """Eski format (faqat balance) yoki buzuq sana — yozuv baribir yaratiladi."""
    b1 = iiko_env["b1"]
    run_sync(db, monkeypatch, {
        TG1: {P_BURGER: {"balance": 0.0, "date_add": "buzuq-sana"}}, TG2: {}})
    e = db.query(models.StopEntry).filter(
        models.StopEntry.branch_id == b1.id,
        models.StopEntry.resolved == False).one()
    assert e.created_at is not None


# ---------- bitta xabarda hamma taom nomi ----------
# Talab: bir vaqtda bir nechta taom stopga tushsa yoki stopdan olinsa, botda
# BITTA xabar kelsin va unda hamma taom nomi ko'rinsin (ilgari 15 tadan keyin
# «…и ещё N» deb kesilardi).

def test_dish_lines_hammasini_korsatadi():
    nomlar = [f"Блюдо {i}" for i in range(40)]
    qatorlar = main._dish_lines(nomlar)
    assert qatorlar[0] == "🍽 Блюда (40):"
    assert len(qatorlar) == 41                       # sarlavha + 40 ta taom
    assert "…и ещё" not in "\n".join(qatorlar)
    assert " • Блюдо 39" in qatorlar


def test_dish_lines_telegram_chegarasida_toxtaydi():
    """4096 belgidan oshib ketmasin — qolgani soni bilan aytiladi."""
    nomlar = [f"Очень длинное название блюда номер {i:03}" for i in range(300)]
    qatorlar = main._dish_lines(nomlar)
    assert len("\n".join(qatorlar)) < main.TG_TEXT_LIMIT
    assert qatorlar[-1].startswith(" • …и ещё")


def test_bir_nechta_stop_bitta_xabarda(db, iiko_env, monkeypatch):
    """Uchta taom birga stopga tushsa — bitta xabar, uchala nomi bilan."""
    P3 = "44444444-4444-4444-4444-444444444444"
    monkeypatch.setitem(NAMES, P3, "Третье из iiko")
    run_sync(db, monkeypatch, {TG1: {}, TG2: {}})            # birinchi sinxron jim
    iiko_env["sent"].clear()

    run_sync(db, monkeypatch, {
        TG1: {P_BURGER: 0.0, P_FRIES: 0.0, P3: 0.0}, TG2: {}})
    assert len(iiko_env["sent"]) == 1, "har bir taomga alohida xabar ketmasin"
    text = iiko_env["sent"][0][1]
    assert "Блюда (3):" in text
    for nom in ("Бургер из iiko", "Картофель из iiko", "Третье из iiko"):
        assert nom in text


def test_bir_nechta_yechim_bitta_xabarda(db, iiko_env, monkeypatch):
    """Uchtasi birga stopdan olinsa ham — bitta xabar, uchala nomi bilan."""
    run_sync(db, monkeypatch, {TG1: {}, TG2: {}})
    run_sync(db, monkeypatch, {TG1: {P_BURGER: 0.0, P_FRIES: 0.0}, TG2: {}})
    iiko_env["sent"].clear()

    run_sync(db, monkeypatch, {TG1: {}, TG2: {}}, alive={TG1, TG2})
    assert len(iiko_env["sent"]) == 1
    text = iiko_env["sent"][0][1]
    assert "Блюда (2):" in text
    assert "Бургер из iiko" in text and "Картофель из iiko" in text
