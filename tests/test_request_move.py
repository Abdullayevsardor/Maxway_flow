"""Zayavkani boshqa kategoriyaga o'tkazish.

Filial zayavkani xato kategoriyaga yuborib qo'yishi mumkin. O'sha kategoriyaga
qaraydigan xodim (admin/menejer/ijrochi) uni to'g'ri kategoriyaga o'tkazadi —
va yangi kategoriya xodimlariga botdan xabar borishi SHART, aks holda zayavka
hech kimga ko'rinmay qolib ketadi.
"""
import pytest

from conftest import login
import main
from app import models


@pytest.fixture
def tg(monkeypatch):
    """Telegram'ni ushlaymiz: (chat_id, matn) juftliklari. Fon oqimi — darhol."""
    sent = []
    monkeypatch.setattr(main, "send_telegram",
                        lambda cid, text, **kw: sent.append((cid, text)))
    monkeypatch.setattr(main, "_send_async",
                        lambda ids, text, button_url="", token="":
                        [main.send_telegram(c, text) for c in ids])
    return sent


@pytest.fixture(scope="module")
def dep_it(db):
    return db.query(models.Department).filter(models.Department.name == "IT").first()


@pytest.fixture(scope="module")
def tech(db):
    """«Техническая» kategoriyasi + uning ijrochisi (telegram bilan)."""
    dep = models.Department(name="Техническая")
    db.add(dep)
    db.flush()
    sub = models.Subcategory(name="Кондиционер", department_id=dep.id)
    ij = models.User(full_name="Техник Темур", email="tech_move@t.uz",
                     hashed_password="x", role=models.Role.executor,
                     department_id=dep.id, is_active=True,
                     telegram_chat_id="TECH")
    db.add_all([sub, ij])
    db.commit()
    return {"dep": dep, "sub": sub, "user": ij}


@pytest.fixture(scope="module")
def it_user(db, dep_it):
    """IT kategoriyasi xodimi — o'tkazilgandan keyin xabar shu odamga boradi."""
    u = models.User(full_name="Айтишник Азиз", email="it_move@t.uz",
                    hashed_password="x", role=models.Role.executor,
                    department_id=dep_it.id, is_active=True,
                    telegram_chat_id="IT")
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def req(db, seed, tech):
    """Filial «Техническая» ga yuborgan zayavka (aslida IT ishi)."""
    r = models.Request(title="Не работает принтер", description="",
                       department_id=tech["dep"].id,
                       subcategory_id=tech["sub"].id,
                       created_by=seed["branch"].id, branch_id=seed["b1"].id,
                       status=models.Status.approved)
    r.assignees.append(tech["user"])
    r.assigned_to = tech["user"].id
    db.add(r)
    db.commit()
    yield r
    db.query(models.Notification).filter(
        models.Notification.link == f"/requests/{r.id}").delete(
            synchronize_session=False)
    db.delete(r)
    db.commit()


def test_route_mavjud():
    assert "/requests/{req_id}/move" in {getattr(x, "path", "")
                                        for x in main.app.routes}


def test_ruxsat_standartlari(db, seed, tech):
    """Admin/menejer/ijrochi — o'tkazadi; filial/viewer — yo'q."""
    assert main.has_perm(seed["admin"], "move_request")
    assert main.has_perm(seed["supply"], "move_request")      # menejer
    assert main.has_perm(tech["user"], "move_request")        # ijrochi
    assert not main.has_perm(seed["branch"], "move_request")  # filial
    assert not main.has_perm(seed["viewer"], "move_request")


def test_filial_otkazolmaydi(client, db, seed, req, tech, dep_it, tg):
    c = login(client, seed["branch"])
    c.post(f"/requests/{req.id}/move",
           data={"department_id": dep_it.id}, follow_redirects=False)
    db.refresh(req)
    assert req.department_id == tech["dep"].id   # kategoriya o'zgarmagan
    assert not tg


def test_ijrochi_otkazadi(client, db, seed, req, tech, dep_it, tg):
    """Kategoriya o'zgaradi, ijrochilar olinadi, status «Новая» ga qaytadi."""
    c = login(client, tech["user"])
    resp = c.post(f"/requests/{req.id}/move",
                  data={"department_id": dep_it.id, "reason": "Это по IT"},
                  follow_redirects=False)
    assert resp.status_code == 302
    db.refresh(req)
    assert req.department_id == dep_it.id
    assert req.subcategory_id is None        # eski kategoriya podkategoriyasi
    assert req.status == models.Status.new
    assert req.assignees == [] and req.assigned_to is None
    assert req.dep_number                     # yangi kategoriyada raqam berilgan
    # tarix va izohda nima bo'lgani yozilgan
    notes = [h.note for h in req.history]
    assert any("Техническая" in n and "IT" in n for n in notes), notes
    texts = [c_.text for c_ in req.comments]
    assert any("Техническая" in t and "IT" in t for t in texts), texts
    assert any("Это по IT" in t for t in texts), texts


def test_yangi_kategoriya_botdan_xabar_oladi(client, db, seed, req, tech,
                                             dep_it, it_user, tg):
    c = login(client, tech["user"])
    c.post(f"/requests/{req.id}/move",
           data={"department_id": dep_it.id, "reason": "Это по IT"},
           follow_redirects=False)
    xabarlar = dict(tg)
    assert "IT" in xabarlar, f"yangi kategoriya xodimiga xabar ketmadi: {tg}"
    matn = xabarlar["IT"]
    assert "переведена" in matn
    assert "Не работает принтер" in matn
    assert "Техническая" in matn and "IT" in matn
    assert "Это по IT" in matn
    # o'tkazgan odamning o'ziga xabar ketmaydi
    assert "TECH" not in xabarlar
    # saytda ham bildirishnoma paydo bo'ladi
    n = db.query(models.Notification).filter(
        models.Notification.user_id == it_user.id,
        models.Notification.link == f"/requests/{req.id}").all()
    assert n and "переведена" in n[0].text


def test_togri_podkategoriya_saqlanadi(client, db, seed, req, tech, dep_it, tg):
    """Yangi kategoriyaning podkategoriyasi tanlansa — o'rnatiladi."""
    sub = models.Subcategory(name="Принтеры", department_id=dep_it.id)
    db.add(sub)
    db.commit()
    c = login(client, tech["user"])
    c.post(f"/requests/{req.id}/move",
           data={"department_id": dep_it.id, "subcategory_id": sub.id},
           follow_redirects=False)
    db.refresh(req)
    assert req.subcategory_id == sub.id


def test_otasi_boshqa_kategoriyadagi_podkategoriya_tushib_qoladi(
        client, db, seed, req, tech, dep_it, tg):
    """Begona podkategoriya yuborilsa — jim tushib qoladi, xato holat yo'q."""
    c = login(client, tech["user"])
    c.post(f"/requests/{req.id}/move",
           data={"department_id": dep_it.id, "subcategory_id": tech["sub"].id},
           follow_redirects=False)
    db.refresh(req)
    assert req.department_id == dep_it.id
    assert req.subcategory_id is None


def test_osha_kategoriyaga_otkazilmaydi(client, db, seed, req, tech, tg):
    c = login(client, tech["user"])
    resp = c.post(f"/requests/{req.id}/move",
                  data={"department_id": tech["dep"].id}, follow_redirects=False)
    assert "err=" in resp.headers["location"]
    assert not tg


def test_boshqa_bolim_zayavkasini_otkazolmaydi(client, db, seed, req, tech,
                                               dep_it, it_user, tg):
    """IT xodimi «Техническая» zayavkasini o'tkazolmaydi — u uni ko'rmaydi ham."""
    c = login(client, it_user)
    c.post(f"/requests/{req.id}/move",
           data={"department_id": dep_it.id}, follow_redirects=False)
    db.refresh(req)
    assert req.department_id == tech["dep"].id
    assert not tg
