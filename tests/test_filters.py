"""Dashboard va Заявки sahifalaridagi filtrlar.

Asosiy talab: filtr barcha rollarda, shu jumladan КПП da ham ko'rinadi,
va КПП faqat unga biriktirilgan filiallar bo'yicha ma'lumot ko'radi.
"""
import pytest

from conftest import login
from app import models, auth


@pytest.fixture(scope="module")
def kpp_setup(db, seed):
    """КПП (faqat b1) + har bir filialda bittadan zayavka."""
    kpp = models.User(full_name="kpp_filter", email="kpp_filter@t.uz",
                      hashed_password=auth.hash_password("test12345"),
                      role=models.Role.kpp, is_active=True)
    kpp.visible_branches = [seed["b1"]]
    db.add(kpp)

    r1 = models.Request(title="Кондиционер не работает", department_id=seed["dep_supply"].id,
                        created_by=seed["branch"].id, branch_id=seed["b1"].id)
    r2 = models.Request(title="Протекает кран на кухне", department_id=seed["dep_supply"].id,
                        created_by=seed["branch2"].id, branch_id=seed["b2"].id)
    db.add_all([r1, r2])
    db.commit()
    return {"kpp": kpp, "r1": r1, "r2": r2}


# ---------- Dashboard ----------
def test_dashboard_filter_visible_for_kpp(client, seed, kpp_setup):
    """Ilgari filtr KPP blokidan tashqarida edi — endi КПП ham ko'radi."""
    login(client, kpp_setup["kpp"])
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert 'action="/dashboard"' in r.text, "filtr formasi КПП uchun ham bo'lishi kerak"
    assert 'name="branch_id"' in r.text
    assert 'name="date_from"' in r.text


def test_dashboard_branch_list_scoped_for_kpp(client, seed, kpp_setup):
    login(client, kpp_setup["kpp"])
    r = client.get("/dashboard")
    assert "Ресторан №12" in r.text
    assert "Ресторан №7" not in r.text, "begona filial nomi ro'yxatda ko'rinmasligi kerak"


def test_dashboard_filter_works_for_kpp(client, seed, kpp_setup):
    """Filtr qo'llanganda КПП natijalar panelini ko'radi (guruhlar o'rniga)."""
    login(client, kpp_setup["kpp"])
    r = client.get(f"/dashboard?branch_id={seed['b1'].id}")
    assert "Результаты фильтра" in r.text
    assert "Кондиционер не работает" in r.text
    assert "Протекает кран" not in r.text


def test_dashboard_kpp_groups_still_shown_without_filter(client, seed, kpp_setup):
    """Filtrsiz — eski ko'rinish (filial bo'yicha guruhlar) saqlanadi."""
    login(client, kpp_setup["kpp"])
    r = client.get("/dashboard")
    assert "Кондиционер не работает" in r.text
    assert "Результаты фильтра" not in r.text


def test_dashboard_kpp_cannot_reach_other_branch(client, seed, kpp_setup):
    login(client, kpp_setup["kpp"])
    r = client.get(f"/dashboard?branch_id={seed['b2'].id}")
    assert "Протекает кран" not in r.text


# ---------- Заявки ----------
def test_requests_filter_rendered(client, seed, kpp_setup):
    """Zayavkalar sahifasida filtr paneli umuman yo'q edi."""
    login(client, seed["admin"])
    r = client.get("/requests")
    assert r.status_code == 200
    assert 'id="reqFilter"' in r.text
    assert 'name="branch_id"' in r.text
    assert 'name="assignee"' in r.text


def test_requests_branch_filter_works(client, seed, kpp_setup):
    """Filial bo'yicha filtr backendda ham ishlaydi (avval e'tiborsiz qolardi)."""
    login(client, seed["admin"])
    r = client.get(f"/requests?branch_id={seed['b1'].id}")
    assert "Кондиционер не работает" in r.text
    assert "Протекает кран" not in r.text


def test_requests_filter_visible_and_scoped_for_kpp(client, seed, kpp_setup):
    login(client, kpp_setup["kpp"])
    r = client.get("/requests")
    assert 'id="reqFilter"' in r.text
    assert "Ресторан №12" in r.text
    assert "Ресторан №7" not in r.text
    assert "Кондиционер не работает" in r.text
    assert "Протекает кран" not in r.text


def test_requests_search_filter(client, seed, kpp_setup):
    login(client, seed["admin"])
    r = client.get("/requests?q=Протекает")
    assert "Протекает кран" in r.text
    assert "Кондиционер не работает" not in r.text


def test_requests_status_kept_when_filtering(client, seed, kpp_setup):
    """Status tabi tanlangan bo'lsa, filtr formasi uni yashirin maydonda saqlaydi."""
    login(client, seed["admin"])
    r = client.get("/requests?status=new")
    assert '<input type="hidden" name="status" value="new">' in r.text


@pytest.mark.parametrize("who", ["admin", "branch", "viewer", "supply"])
def test_dashboard_still_ok_for_other_roles(client, seed, kpp_setup, who):
    """Shablon qayta tuzilgandan keyin qolgan rollarda regressiya yo'qligini tekshiramiz."""
    login(client, seed[who])
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert 'action="/dashboard"' in r.text            # filtr joyida
    assert "Последние заявки" in r.text               # filtrsiz — odatiy ko'rinish
    r2 = client.get("/dashboard?date_from=2020-01-01")
    assert "Результаты фильтра" in r2.text            # filtr bilan — natijalar
