"""Filiallarni iiko'ga avtomatik bog'lash (nomi bo'yicha).

20 ta filialga qo'lda GUID kiritish uzoq va xato qilish oson — production'da
aynan shunday bo'ldi: maydonlarga GUID o'rniga terminal guruh NOMI yozilib
qoldi va sinxron hech narsa topa olmadi.
"""
import main


def g(gid, name):
    return {"id": gid, "name": name}


def test_kiril_lotinga_ogiriladi():
    """iiko'da «Универсам», bizda «UNIVERSAM» — solishtirish uchun bir xil."""
    assert main._iiko_key("Универсам") == "UNIVERSAM"
    assert main._iiko_key("MW-HADRA Зал") == "MWHADRAZAL"
    assert main._iiko_key("З А Л") == "ZAL"


def test_filial_nomidan_bolak_ajratiladi():
    assert main._iiko_branch_tail("MW01-UNIVERSAM") == "UNIVERSAM"
    assert main._iiko_branch_tail("MW22-ECO CHIMGAN") == "ECOCHIMGAN"


def test_bitta_tashkilotdagi_ikki_nuqta_ajratiladi():
    """MW01 tashkilotida «Универсам» ham, «Фонтан» ham bor — filial nomiga
    mos kelgani tanlanishi kerak, aks holda stoplar aralashib ketadi."""
    groups = [g("f1", "Max Way Фонтан"), g("u1", "Max Way Универсам")]
    pick, _ = main._iiko_pick_group("MW01-UNIVERSAM", groups, {"f1", "u1"})
    assert pick["id"] == "u1"

    pick, _ = main._iiko_pick_group("MW01-FONTAN", groups, {"f1", "u1"})
    assert pick["id"] == "f1"


def test_tirik_kassa_afzal_koriladi():
    groups = [g("a", "Доставка"), g("b", "Зал")]
    pick, _ = main._iiko_pick_group("MW10-PARKENT", groups, {"a"})
    assert pick["id"] == "a"        # «Зал» bo'lsa ham o'lik — tirigini olamiz


def test_zal_afzal_koriladi():
    groups = [g("a", "С собой"), g("b", "Зал")]
    pick, _ = main._iiko_pick_group("MW10-PARKENT", groups, {"a", "b"})
    assert pick["id"] == "b"


def test_ikkilanish_belgilanadi():
    """Ikki nomzod bir xil ballga ega bo'lsa — odam ko'rib chiqishi kerak."""
    groups = [g("a", "MasterFood-Rossiya"), g("b", "Касса собой")]
    _, shubhali = main._iiko_pick_group("MW03-GRAND MIR", groups, {"a", "b"})
    assert shubhali is True

    groups = [g("a", "С собой"), g("b", "Зал")]
    _, shubhali = main._iiko_pick_group("MW10-PARKENT", groups, {"a", "b"})
    assert shubhali is False


def test_guruh_yoq_bolsa_none():
    pick, shubhali = main._iiko_pick_group("MW01-UNIVERSAM", [], set())
    assert pick is None and shubhali is False


def test_admin_iiko_boglanishni_uza_oladi(client, seed, db):
    """«— не связан —» ni tanlash haqiqatan uzishi kerak.

    Ilgari bu tanlov bo'sh matn yuborardi, FastAPI esa bo'sh matnli Form
    maydonini «yuborilmagan» deb None ga aylantirardi — natijada uzish
    buyrug'i yo'qolib, filial iiko'ga bog'langanicha qolaverardi."""
    from conftest import login
    b = seed["b2"]
    b.iiko_terminal_id = "tg-777"
    b.iiko_org_id = "org-1"
    b.iiko_terminal_name = "Зал"
    db.commit()

    login(client, seed["admin"])
    r = client.post(f"/admin/branches/{b.id}/edit",
                    data={"name": b.name, "iiko_bind": "-"}, follow_redirects=False)
    assert r.status_code == 302
    db.rollback()
    db.refresh(b)
    assert b.iiko_terminal_id == ""
    assert b.iiko_org_id == ""


def test_admin_iiko_maydonsiz_sorov_boglanishga_tegmaydi(client, seed, db):
    """iiko_bind umuman yuborilmasa — mavjud bog'lanish saqlanadi."""
    from conftest import login
    b = seed["b2"]
    b.iiko_terminal_id = "tg-888"
    db.commit()
    login(client, seed["admin"])
    client.post(f"/admin/branches/{b.id}/edit", data={"name": b.name},
                follow_redirects=False)
    db.rollback()
    db.refresh(b)
    assert b.iiko_terminal_id == "tg-888"
    b.iiko_terminal_id = ""
    db.commit()
