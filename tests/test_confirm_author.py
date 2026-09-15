"""Sabab tasdig'i: KIM tasdiqlagani ro'yxatda rol bo'yicha ko'rinadi.

Stop-listda odamning ismi emas, qaysi TOMON tasdiqlagani muhim: КПП mi,
Снабжение mi. Ikkalasiga ham kirmaydigan (admin alohida ruxsat bergan) xodim
o'z ismi bilan ko'rinadi.
"""
import json
import re

import pytest

from conftest import login
import main
from app import models


@pytest.fixture(scope="module")
def kpp(db, seed):
    """КПП foydalanuvchisi — b1 filialini ko'radi va tasdiqlay oladi."""
    u = models.User(full_name="Anton Rudnikov", email="kpp_author@t.uz",
                    hashed_password="x", role=models.Role.kpp, is_active=True,
                    perms=json.dumps({"view_stop": True, "confirm_stop": True}))
    u.visible_branches.append(seed["b1"])
    db.add(u)
    db.commit()
    return u


@pytest.fixture(scope="module")
def entry(db, seed):
    """b1 filialida bitta ochiq yozuv."""
    mi = models.MenuItem(name="Сок апельсиновый", is_active=True)
    db.add(mi)
    db.flush()
    e = models.StopEntry(branch_id=seed["b1"].id, menu_item_id=mi.id,
                         reason="supplier_stop", created_by=seed["branch"].id,
                         created_at=models.tashkent_now())
    db.add(e)
    db.commit()
    return e


def _reset(db, e):
    e.supply_confirmed = False
    e.confirmed_by = None
    e.confirmed_at = None
    db.commit()


# ---------- actor_label ----------
def test_actor_label_snabjenie(seed):
    assert main.actor_label(seed["supply"]) == "Снабжение"


def test_actor_label_kpp(kpp):
    assert main.actor_label(kpp) == "КПП"


def test_actor_label_boshqa_odam_ismi_bilan(seed):
    """Rol/bo'limga tushmagan (alohida ruxsat berilgan) xodim — ismi bilan."""
    assert main.actor_label(seed["admin"]) == seed["admin"].full_name


def test_actor_label_prosmotr_ismi_bilan(seed):
    """Просмотр roli — КПП ham, Снабжение ham emas, shuning uchun ism chiqadi
    (masalan «Anton Rudnikov»)."""
    assert main.actor_label(seed["viewer"]) == seed["viewer"].full_name


def test_actor_label_none():
    assert main.actor_label(None) == ""


# ---------- ro'yxatda ko'rinishi ----------
def _confirm(client, db, seed, e, who):
    """`who` yozuvni tasdiqlaydi, keyin ro'yxat ADMIN ko'zi bilan qaytariladi.

    Admin bilan qaralishi muhim: tasdiqlagan odamning ismi yon panelda
    («kim kirgan») turadi va «ism ko'rinmasin» sinovini yolg'on buzardi."""
    _reset(db, e)
    login(client, who)
    client.post(f"/stoplist/{e.id}/confirm", data={"supply_confirmed": "1"},
                follow_redirects=False)
    db.refresh(e)
    assert e.supply_confirmed and e.confirmed_by == who.id
    login(client, seed["admin"])


def _labels(html):
    """Ro'yxatdagi barcha «kim tasdiqladi» yorliqlari."""
    return [m.strip() for m in
            re.findall(r'class="cmt-by"[^>]*>(.*?)</div>', html, re.S)]


def test_snabjenie_tasdiqlasa_royxatda_korinadi(client, db, seed, entry):
    _confirm(client, db, seed, entry, seed["supply"])
    labels = _labels(client.get("/stoplist").text)
    assert "✓ Снабжение" in labels
    assert not any(seed["supply"].full_name in l for l in labels),         "ism emas, bo'lim ko'rinishi kerak"


def test_kpp_tasdiqlasa_royxatda_kpp_korinadi(client, db, seed, entry, kpp):
    _confirm(client, db, seed, entry, kpp)
    labels = _labels(client.get("/stoplist").text)
    assert "✓ КПП" in labels
    assert not any("Anton Rudnikov" in l for l in labels)


def test_tasdiqlanmagan_yozuvda_yorliq_yoq(client, db, seed, entry):
    _reset(db, entry)
    login(client, seed["supply"])
    assert "cmt-by" not in client.get("/stoplist").text


def test_detal_sahifada_ham_rol_korinadi(client, db, seed, entry, kpp):
    _confirm(client, db, seed, entry, kpp)
    html = client.get(f"/stoplist/{entry.id}").text
    assert "· КПП" in html
    assert "Anton Rudnikov" not in html, "sahifada ism emas, rol turishi kerak"


def test_sozdal_va_izmeneno_qatorlari_yoq(client, seed, entry):
    """Yozuv sahifasida «Создал» va «Изменено» qatorlari ko'rsatilmaydi —
    ro'yxatni iiko to'ldiradi, bu qatorlar odamga hech narsa bermasdi."""
    login(client, seed["admin"])
    html = client.get(f"/stoplist/{entry.id}").text
    assert "Создал" not in html
    assert "Изменено" not in html


# ---------- yorliq matni ----------
def test_static_snabjenie_sozi_olib_tashlandi(client, seed, entry):
    """«Подтверждение причины стопа» — «отделом снабжения» qismisiz,
    izoh esa shunchaki «Комментарий»."""
    login(client, seed["supply"])
    html = client.get(f"/stoplist/{entry.id}").text
    assert "Подтверждение причины стопа" in html
    assert "отделом снабжения" not in html
    assert "Комментарий снабжения" not in html


def test_royxat_ustuni_shunchaki_kommentariy(client, seed, entry):
    """Jadval sarlavhasida ham «Комм. снабжения» emas — «Комментарий»."""
    login(client, seed["supply"])
    html = client.get("/stoplist").text
    assert "Комм. снабжения" not in html
    assert 'Комментарий<span class="sort-ar"' in html
    # tarix sahifasi bo'sh bo'lishi mumkin (jadval umuman chizilmaydi),
    # shuning uchun u yerda faqat eski nom qolmaganini tekshiramiz
    assert "Комм. снабжения" not in client.get("/stoplist/history").text
