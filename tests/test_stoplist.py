"""Стоп-лист (Причины стопов по продуктам по филиалам) — backend testlari.

Qamrov: yaratish, ro'yxat, detal, tahrirlash, filtr, saralash, pagination,
ruxsatlar (403) va Excel eksport.
"""
import io

import pytest

from conftest import login
from app import models


# ---------- yordamchilar ----------
def api_create(client, product_id, branch_id=None, reason="supplier_no_product",
               comment="Поставка задерживается", **kw):
    body = {"product_id": product_id, "reason": reason, "branch_comment": comment}
    if branch_id:
        body["branch_id"] = branch_id
    body.update(kw)
    return client.post("/api/product-stops", json=body)


# ================= SCENARIO 2 — создание =================
def test_create_sets_created_by_and_at_on_backend(client, seed, db):
    """Filial yozuv yaratadi; created_at/created_by faqat backend tomonidan qo'yiladi."""
    login(client, seed["branch"])
    r = api_create(client, seed["dishes"][0].id,
                   # frontend soxta qiymat yubormoqchi — backend e'tiborsiz qoldirishi kerak
                   created_by=seed["admin"].id, created_at="2000-01-01 00:00")
    assert r.status_code == 201, r.text
    item = r.json()["created"][0]
    assert item["branch"] == "Ресторан №12"
    assert item["product"] == "Бургер Классик"
    assert item["reason_label"] == "Нет продукта у поставщика"
    assert item["created_by"] == seed["branch"].id      # soxta created_by qabul qilinmadi
    assert not item["created_at"].startswith("2000")   # soxta created_at qabul qilinmadi
    assert item["supply_confirmed"] is False


def test_create_appears_in_list(client, seed):
    login(client, seed["branch"])
    r = client.get("/api/product-stops")
    assert r.status_code == 200
    names = [i["product"] for i in r.json()["items"]]
    assert "Бургер Классик" in names


def test_duplicate_is_skipped_not_duplicated(client, seed):
    """Bir filialda ayni taom ikki marta faol stopga tushmaydi."""
    login(client, seed["branch"])
    r = api_create(client, seed["dishes"][0].id)
    assert r.status_code == 201
    assert r.json()["created"] == []
    assert r.json()["skipped"] == ["Бургер Классик"]


# ================= SCENARIO 3 — validatsiya =================
@pytest.mark.parametrize("payload, expect", [
    ({"reason": "supplier_no_product"}, "Блюдо"),
    ({"product_id": 1}, "Причина"),
    ({"product_id": 1, "reason": "не_существует"}, "справочник"),
    ({"product_id": 999999, "reason": "supplier_no_product"}, "Блюдо не найдено"),
])
def test_validation_rejects_bad_input(client, seed, payload, expect):
    login(client, seed["branch"])
    r = client.post("/api/product-stops", json=payload)
    assert r.status_code == 400
    assert expect.lower() in r.json()["detail"].lower()


def test_validation_rejects_too_long_comment(client, seed):
    login(client, seed["branch"])
    r = api_create(client, seed["dishes"][1].id, comment="x" * 1001)
    assert r.status_code == 400
    assert "максимум" in r.json()["detail"]


def test_admin_must_pass_existing_branch(client, seed):
    login(client, seed["admin"])
    r = client.post("/api/product-stops", json={
        "product_id": seed["dishes"][1].id, "reason": "wrong_order", "branch_id": 999999})
    assert r.status_code == 400
    assert "Филиал не найден" in r.json()["detail"]


# ================= SCENARIO 4 — просмотр =================
def test_detail_shows_all_fields(client, seed, db):
    login(client, seed["branch"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    r = client.get(f"/api/product-stops/{sid}")
    assert r.status_code == 200
    d = r.json()
    for key in ("id", "created_at", "branch", "product", "reason_label",
                "branch_comment", "supply_confirmed", "supply_comment",
                "created_by_name", "updated_at"):
        assert key in d
    # HTML detal sahifasi ham ochiladi
    page = client.get(f"/stoplist/{sid}")
    assert page.status_code == 200
    assert "Информация о стопе" in page.text


def test_branch_cannot_view_other_branch_record(client, seed):
    """Filial boshqa filial yozuvini ko'ra olmaydi (403)."""
    login(client, seed["admin"])
    r = api_create(client, seed["dishes"][2].id, branch_id=seed["b2"].id,
                   reason="equipment_broken")
    other_id = r.json()["created"][0]["id"]
    login(client, seed["branch"])                    # 12-filial
    assert client.get(f"/api/product-stops/{other_id}").status_code == 403
    assert client.get(f"/stoplist/{other_id}").status_code == 403


def test_branch_list_is_scoped_to_own_branch(client, seed):
    login(client, seed["branch"])
    items = client.get("/api/product-stops").json()["items"]
    assert items and all(i["branch"] == "Ресторан №12" for i in items)


# ================= SCENARIO 5 — редактирование =================
def test_edit_updates_updated_at_and_by(client, seed):
    login(client, seed["branch"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    assert client.get(f"/api/product-stops/{sid}").json()["updated_at"] is None
    r = client.patch(f"/api/product-stops/{sid}",
                     json={"branch_comment": "Поставка сегодня к 16:00"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["branch_comment"] == "Поставка сегодня к 16:00"
    assert d["updated_at"] is not None
    assert d["updated_by"] == seed["branch"].id


def test_edit_rejects_unknown_reason(client, seed):
    login(client, seed["branch"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    r = client.patch(f"/api/product-stops/{sid}", json={"reason": "нет_такой"})
    assert r.status_code == 400


# ================= SCENARIO 6 + 11 — подтверждение снабжения =================
def test_supply_can_confirm(client, seed):
    login(client, seed["supply"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    r = client.patch(f"/api/product-stops/{sid}", json={
        "supply_confirmed": True, "supply_comment": "Поставка ожидается сегодня до 16:00"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["supply_confirmed"] is True
    assert d["supply_comment"] == "Поставка ожидается сегодня до 16:00"
    assert d["confirmed_at"] is not None
    assert d["confirmed_by_name"] == "supply"


def test_branch_cannot_confirm_via_direct_api(client, seed):
    """SCENARIO 11 — ruxsatsiz foydalanuvchi to'g'ridan-to'g'ri API orqali 403 oladi."""
    login(client, seed["branch"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    before = client.get(f"/api/product-stops/{sid}").json()["supply_confirmed"]
    r = client.patch(f"/api/product-stops/{sid}", json={"supply_confirmed": True})
    assert r.status_code == 403
    # forma endpointi ham himoyalangan
    r2 = client.post(f"/stoplist/{sid}/confirm", data={"supply_confirmed": "1"})
    assert r2.status_code == 403
    # va qiymat o'zgarmagan
    assert client.get(f"/api/product-stops/{sid}").json()["supply_confirmed"] is before


def test_supply_cannot_edit_branch_fields(client, seed):
    login(client, seed["supply"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    r = client.patch(f"/api/product-stops/{sid}", json={"branch_comment": "чужое поле"})
    assert r.status_code == 403


def test_viewer_cannot_create_or_edit(client, seed):
    login(client, seed["viewer"])
    assert api_create(client, seed["dishes"][3].id).status_code == 403
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    assert client.patch(f"/api/product-stops/{sid}",
                        json={"supply_comment": "x"}).status_code == 403


def test_client_without_branch_sees_nothing(client, seed, db):
    """Filialga biriktirilmagan klient hech qanday yozuv ko'rmaydi."""
    from app import auth as _auth
    u = models.User(full_name="no-branch", email="nobranch@t.uz",
                    hashed_password=_auth.hash_password("test12345"),
                    role=models.Role.client, is_active=True)
    db.add(u); db.commit()
    login(client, u)
    assert client.get("/api/product-stops").json()["total"] == 0
    assert client.get("/stoplist").status_code == 200


def test_anonymous_gets_401(client, seed):
    client.cookies.clear()
    assert client.get("/api/product-stops").status_code == 401
    assert client.post("/api/product-stops", json={}).status_code == 401


# ================= SCENARIO 7 — фильтрация =================
def test_filter_by_branch_reason_and_confirmation(client, seed):
    login(client, seed["admin"])
    # 7-filialga yana bitta yozuv
    api_create(client, seed["dishes"][3].id, branch_id=seed["b2"].id, reason="menu_removed")

    by_branch = client.get(f"/api/product-stops?branch_id={seed['b2'].id}").json()
    assert by_branch["items"] and all(i["branch"] == "Ресторан №7" for i in by_branch["items"])

    by_reason = client.get("/api/product-stops?reason=menu_removed").json()
    assert all(i["reason"] == "menu_removed" for i in by_reason["items"])
    assert by_reason["total"] >= 1

    conf_yes = client.get("/api/product-stops?confirmed=yes").json()
    assert all(i["supply_confirmed"] is True for i in conf_yes["items"])
    conf_no = client.get("/api/product-stops?confirmed=no").json()
    assert all(i["supply_confirmed"] is False for i in conf_no["items"])
    assert conf_yes["total"] + conf_no["total"] == client.get("/api/product-stops").json()["total"]


def test_filter_by_product_and_date_range(client, seed):
    login(client, seed["admin"])
    pid = seed["dishes"][0].id
    d = client.get(f"/api/product-stops?menu_item_id={pid}").json()
    assert d["items"] and all(i["product_id"] == pid for i in d["items"])

    today = models.tashkent_now().strftime("%Y-%m-%d")
    assert client.get(f"/api/product-stops?date_from={today}&date_to={today}").json()["total"] >= 1
    assert client.get("/api/product-stops?date_from=1999-01-01&date_to=1999-01-02").json()["total"] == 0


def test_invalid_filter_is_ignored_not_crashing(client, seed):
    login(client, seed["admin"])
    r = client.get("/api/product-stops?branch_id=abc&reason=' OR 1=1--&date_from=не-дата")
    assert r.status_code == 200
    assert r.json()["total"] == client.get("/api/product-stops").json()["total"]


# ================= SCENARIO 8 — сортировка =================
def test_sorting_asc_and_desc(client, seed):
    login(client, seed["admin"])
    asc = [i["product"] for i in
           client.get("/api/product-stops?sort_by=dish&sort_order=asc").json()["items"]]
    desc = [i["product"] for i in
            client.get("/api/product-stops?sort_by=dish&sort_order=desc").json()["items"]]
    assert asc == sorted(asc)
    assert desc == list(reversed(asc))

    dates = [i["created_at"] for i in
             client.get("/api/product-stops?sort_by=created_at&sort_order=asc").json()["items"]]
    assert dates == sorted(dates)


def test_unknown_sort_field_falls_back(client, seed):
    """Oq ro'yxatda yo'q ustun — standart tartibga qaytadi (SQL injection imkonsiz)."""
    login(client, seed["admin"])
    r = client.get("/api/product-stops?sort_by=id);DROP TABLE stop_entries;--")
    assert r.status_code == 200
    assert r.json()["sort_by"] == "created_at"


# ================= SCENARIO 9 — pagination =================
def test_pagination_meta_and_slicing(client, seed):
    login(client, seed["admin"])
    total = client.get("/api/product-stops").json()["total"]
    assert total >= 3
    p1 = client.get("/api/product-stops?page=1&page_size=10&sort_by=created_at&sort_order=asc").json()
    assert p1["page"] == 1 and p1["page_size"] == 10
    assert p1["pages"] == max(1, -(-total // 10))
    assert len(p1["items"]) <= 10

    small = client.get("/api/product-stops?page=1&page_size=10").json()
    assert small["page_size"] == 10
    # ruxsat etilmagan page_size — standartga qaytadi
    assert client.get("/api/product-stops?page_size=7").json()["page_size"] == 25
    # chegaradan tashqari sahifa — oxirgi sahifaga qisiladi
    assert client.get("/api/product-stops?page=9999").json()["page"] == small["pages"]
    assert client.get("/api/product-stops?page=-3").json()["page"] == 1


def test_pages_do_not_overlap(client, seed):
    login(client, seed["admin"])
    base = "/api/product-stops?page_size=10&sort_by=created_at&sort_order=asc&page="
    ids1 = [i["id"] for i in client.get(base + "1").json()["items"]]
    meta = client.get(base + "1").json()
    if meta["pages"] > 1:
        ids2 = [i["id"] for i in client.get(base + "2").json()["items"]]
        assert not set(ids1) & set(ids2)


# ================= SCENARIO 10 — Excel =================
def _read_xlsx(content):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb["Все филиалы"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return rows


def test_export_respects_filters(client, seed):
    login(client, seed["admin"])
    r = client.get(f"/stoplist/export?mode=active&branch_id={seed['b2'].id}")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "product_stops_" in r.headers["content-disposition"]

    rows = _read_xlsx(r.content)
    assert rows[0] == ("Добавлено", "Филиал", "Блюдо", "Причина", "Комментарий Филиала",
                       "Подтверждение причины стопа отделом снабжения", "Комментарий Снабжения")
    body = rows[1:]
    assert body, "экспорт не должен быть пустым"
    assert all(row[1] == "Ресторан №7" for row in body)   # faqat filtrlangan filial
    assert all(row[5] in ("ДА", "НЕТ") for row in body)


def test_export_respects_sorting(client, seed):
    login(client, seed["admin"])
    rows = _read_xlsx(client.get(
        "/stoplist/export?mode=active&sort_by=dish&sort_order=asc").content)[1:]
    dishes = [r[2] for r in rows]
    assert dishes == sorted(dishes)


def test_export_forbidden_without_permission(client, seed, db):
    """export_stop ruxsati olib tashlangan foydalanuvchi 403 oladi."""
    import json as _json
    u = seed["viewer"]
    u.perms = _json.dumps({"export_stop": False})
    db.commit()
    login(client, u)
    assert client.get("/stoplist/export?mode=active").status_code == 403
    u.perms = None
    db.commit()


# ================= HTML sahifalar =================
def test_html_pages_render(client, seed):
    login(client, seed["admin"])
    for url in ("/stoplist", "/stoplist/history",
                "/stoplist?sort_by=dish&sort_order=asc&page_size=10",
                "/stoplist?confirmed=yes&reason=menu_removed"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Причины стопов" in r.text or "История стоп-листа" in r.text


def test_html_add_form_creates_record(client, seed):
    """Forma orqali qo'shish (klient) — ro'yxatда paydo bo'ladi."""
    login(client, seed["branch"])
    r = client.post("/stoplist/add", data={
        "menu_item_id": [str(seed["dishes"][2].id)],
        "reason": "equipment_broken", "comment": "Сломался аппарат"},
        follow_redirects=False)
    assert r.status_code == 302
    assert "ok=" in r.headers["location"]
    items = client.get("/api/product-stops").json()["items"]
    assert any(i["product"] == "Кола 0.5" and i["reason"] == "equipment_broken"
               for i in items)


def test_html_add_without_reason_is_rejected(client, seed):
    login(client, seed["branch"])
    r = client.post("/stoplist/add", data={
        "menu_item_id": [str(seed["dishes"][3].id)], "reason": ""},
        follow_redirects=False)
    assert r.status_code == 302
    assert "err=" in r.headers["location"]


def test_html_edit_form(client, seed):
    login(client, seed["supply"])
    sid = client.get("/api/product-stops").json()["items"][0]["id"]
    r = client.post(f"/stoplist/{sid}/edit", data={
        "fields": "supply_confirmed,supply_comment",
        "supply_confirmed": "1", "supply_comment": "Ждём поставку"},
        follow_redirects=False)
    assert r.status_code == 302
    d = client.get(f"/api/product-stops/{sid}").json()
    assert d["supply_confirmed"] is True and d["supply_comment"] == "Ждём поставку"


def test_resolve_moves_to_history(client, seed):
    login(client, seed["branch"])
    before = client.get("/api/product-stops").json()["items"]
    sid = before[0]["id"]
    r = client.post(f"/stoplist/{sid}/resolve", follow_redirects=False)
    assert r.status_code == 302
    assert sid not in [i["id"] for i in client.get("/api/product-stops").json()["items"]]
    hist = client.get("/api/product-stops?mode=history").json()["items"]
    assert sid in [i["id"] for i in hist]


# ================= спрвочники =================
def test_reference_endpoints(client, seed):
    login(client, seed["admin"])
    reasons = client.get("/api/stop-reasons").json()
    keys = {r["id"] for r in reasons}
    assert {"equipment_broken", "supplier_no_product",
            "wrong_order", "menu_removed"} <= keys
    branch_names = {b["name"] for b in client.get("/api/branches").json()}
    assert {"Ресторан №12", "Ресторан №7"} <= branch_names
    dish_names = {p["name"] for p in client.get("/api/products").json()}
    assert {"Бургер Классик", "Кола 0.5"} <= dish_names

    # klient — faqat o'z filialini ko'radi
    login(client, seed["branch"])
    assert [b["name"] for b in client.get("/api/branches").json()] == ["Ресторан №12"]


# ================= PERFORMANCE — N+1 yo'qligi =================
def test_list_query_count_is_constant(client, seed, db):
    """Ro'yxat sahifasi yozuvlar soniga bog'liq bo'lmagan sonda so'rov qiladi."""
    from sqlalchemy import event
    from app.database import engine

    counter = {"n": 0}

    def before(conn, cursor, statement, params, ctx, many):
        counter["n"] += 1

    login(client, seed["admin"])
    event.listen(engine, "before_cursor_execute", before)
    try:
        counter["n"] = 0
        client.get("/api/product-stops?page_size=100")
        used = counter["n"]
    finally:
        event.remove(engine, "before_cursor_execute", before)
    # 1 — foydalanuvchi, 1 — count, 1 — ro'yxat (branch/menu_item join bilan keladi)
    assert used <= 5, f"слишком много запросов: {used} (возможен N+1)"
