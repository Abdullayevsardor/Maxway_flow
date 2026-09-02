"""Stop-list jadvalidagi tugmalar HAQIQATDA qaysi manzilga yuborishini tekshiradi.

Nega kerak: jadvalni ommaviy «Убрать со стопа» formasi o'rab turadi. Agar qator
formalari jadval ICHIDA yozilsa, HTML forma ichida formaga ruxsat bermagani
uchun brauzer ularni tashlab yuboradi va tugma ommaviy formaga ketadi —
hech qanday xatosiz, jimgina. Oddiy `in r.text` tekshiruvi buni ko'rmaydi,
shuning uchun bu yerda haqiqiy HTML5 parseri (html5lib) ishlatiladi.
"""
import pytest

html5lib = pytest.importorskip("html5lib")

from conftest import login
from app import models


def button_targets(html):
    """Har bir tugma -> yuboradigan manzil. form="..." atributi ustun turadi."""
    doc = html5lib.parse(html, namespaceHTMLElements=False)
    forms = {f.get("id"): f.get("action") for f in doc.findall(".//form")}
    parent = {}
    for p in doc.iter():
        for ch in p:
            parent[ch] = p

    def owner(el):
        fid = el.get("form")
        if fid:
            assert fid in forms, f"'{fid}' formasi sahifada yo'q"
            return forms[fid]
        cur = parent.get(el)
        while cur is not None:
            if cur.tag == "form":
                return cur.get("action")
            cur = parent.get(cur)
        return None

    out = []
    for b in doc.findall(".//button"):
        text = "".join(b.itertext()).strip()
        if text:
            out.append((text, owner(b), b.get("hidden") is not None))
    return out, doc, forms


@pytest.fixture(scope="module")
def rows(db, seed):
    """Supply foydalanuvchisi uchun bir nechta ochiq va bitta yechilgan yozuv."""
    items = []
    for name in ("Кофе латте", "Чай зелёный", "Морс ягодный"):
        mi = models.MenuItem(name=name, is_active=True)
        db.add(mi); db.flush()
        e = models.StopEntry(branch_id=seed["b1"].id, menu_item_id=mi.id,
                             reason="supplier_stop", created_by=seed["branch"].id,
                             created_at=models.tashkent_now())
        db.add(e); items.append(e)
    mi = models.MenuItem(name="Компот вишнёвый", is_active=True)
    db.add(mi); db.flush()
    done = models.StopEntry(branch_id=seed["b1"].id, menu_item_id=mi.id,
                            reason="supplier_stop", created_by=seed["branch"].id,
                            created_at=models.tashkent_now(), resolved=True,
                            resolved_at=models.tashkent_now())
    db.add(done)
    db.commit()
    return {"open": items, "done": done}


def test_no_form_is_swallowed(client, seed, rows):
    """Shablondagi har bir <form> brauzerda ham saqlanib qolishi kerak."""
    login(client, seed["supply"])
    html = client.get("/stoplist").text
    doc = html5lib.parse(html, namespaceHTMLElements=False)
    assert len(doc.findall(".//form")) == html.count("<form"), \
        "forma ichida forma — brauzer birortasini tashlab yubordi"


def test_every_row_button_hits_its_own_endpoint(client, seed, rows):
    """Avval eng yuqoridagi qatorning ДА/НЕТ tugmasi resolve-bulk ga ketardi."""
    login(client, seed["supply"])
    targets, _, _ = button_targets(client.get("/stoplist").text)

    for text, action, _hidden in targets:
        if text in ("ДА", "НЕТ"):
            assert "/confirm" in action, f"«{text}» -> {action}"
        elif text == "Убрать":
            assert "/resolve" in action and "bulk" not in action, f"«{text}» -> {action}"
        elif text == "Сохранить":
            assert "/comment" in action, f"«{text}» -> {action}"

    # har bir ochiq yozuv uchun uchala tugma ham bor
    for e in rows["open"]:
        acts = [a for _t, a, _h in targets if a]
        assert f"/stoplist/{e.id}/confirm" in acts
        assert f"/stoplist/{e.id}/resolve" in acts
        assert f"/stoplist/{e.id}/comment" in acts


def test_default_state_shows_remove_not_save(client, seed, rows):
    """Standart holat: «Убрать» ko'rinadi, «Сохранить» yashirin."""
    login(client, seed["supply"])
    targets, _, _ = button_targets(client.get("/stoplist").text)
    remove = [(t, h) for t, a, h in targets if t == "Убрать"]
    save = [(t, h) for t, a, h in targets if t == "Сохранить"]
    assert remove and all(not hidden for _t, hidden in remove), "«Убрать» ko'rinishi kerak"
    assert save and all(hidden for _t, hidden in save), "«Сохранить» boshida yashirin bo'lishi kerak"


def test_comment_input_bound_to_comment_form(client, seed, rows):
    """Izoh maydoni o'z qatorining comment formasiga bog'langan bo'lishi kerak."""
    login(client, seed["supply"])
    _t, doc, forms = button_targets(client.get("/stoplist").text)
    found = 0
    for inp in doc.findall(".//input"):
        if inp.get("name") == "comment":
            rid = inp.get("data-row")
            assert forms.get(inp.get("form")) == f"/stoplist/{rid}/comment"
            assert inp.get("data-orig") is not None, "boshlang'ich qiymat saqlanishi kerak"
            found += 1
    assert found >= len(rows["open"])


def test_history_buttons_also_bound(client, seed, rows):
    """Tarix sahifasida ham formalar butun va tugmalar to'g'ri bog'langan."""
    login(client, seed["supply"])
    html = client.get("/stoplist/history").text
    doc = html5lib.parse(html, namespaceHTMLElements=False)
    assert len(doc.findall(".//form")) == html.count("<form")
    targets, _, _ = button_targets(html)
    for text, action, _h in targets:
        if text == "Сохранить":
            assert "/comment" in action
        elif text in ("ДА", "НЕТ"):
            assert "/confirm" in action
    assert not any(t == "Убрать" for t, _a, _h in targets), \
        "tarixda «Убрать» bo'lmasligi kerak"


def test_client_without_comment_perm_sees_only_remove(client, seed, rows):
    """Izoh huquqi yo'q filial: faqat «Убрать», izoh maydoni yo'q."""
    login(client, seed["branch"])
    html = client.get("/stoplist").text
    targets, doc, _ = button_targets(html)
    assert any(t == "Убрать" for t, _a, _h in targets)
    assert not any(t == "Сохранить" for t, _a, _h in targets)
    assert not [i for i in doc.findall(".//input") if i.get("name") == "comment"]
