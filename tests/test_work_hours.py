"""Stopda turgan muddat filial ish grafigi bo'yicha hisoblanadi.

Ilgari oddiy ayirma edi: filial yopiq turgan soatlar ham «stopda turdi» deb
sanalardi. Masalan 09:00–03:00 ishlaydigan filialda kechqurun qo'yilgan stop
ertasi kuni yechilsa, oradagi 6 soat yopiqlik ham qo'shilib ketardi.

iiko API grafikni bermaydi (organizations va delivery_restrictions tekshirildi),
shuning uchun u sozlamada saqlanadi va loyiha oynalarida ko'rinmaydi.
"""
from datetime import datetime, timedelta

import main


T = lambda *a: datetime(*a)
KUNDUZ = ((9, 0), (3, 0))          # 09:00 -> 03:00 (yarim tundan o'tadi)


def soat(delta):
    return round(delta.total_seconds() / 3600, 2)


def test_grafik_ichida_toliq_sanaladi():
    d = main.working_delta(T(2026, 9, 9, 10, 0), T(2026, 9, 9, 14, 30), *KUNDUZ)
    assert soat(d) == 4.5


def test_yopiq_soatlar_chiqarib_tashlanadi():
    """01:00 da qo'yilib, 11:00 da yechildi. Astronomik 10 soat, lekin
    03:00–09:00 orasida filial yopiq — faqat 4 soat sanaladi."""
    d = main.working_delta(T(2026, 9, 9, 1, 0), T(2026, 9, 9, 11, 0), *KUNDUZ)
    assert soat(d) == 4.0          # 01:00-03:00 (2 s) + 09:00-11:00 (2 s)


def test_toliq_yopiq_oraliq_nol():
    d = main.working_delta(T(2026, 9, 9, 4, 0), T(2026, 9, 9, 8, 0), *KUNDUZ)
    assert soat(d) == 0.0


def test_bir_necha_kun():
    """09.09 20:00 dan 11.09 20:00 gacha — ikki kunlik ish vaqti.
    Har kuni 18 soat ishlaydi (09:00->03:00)."""
    d = main.working_delta(T(2026, 9, 9, 20, 0), T(2026, 9, 11, 20, 0), *KUNDUZ)
    # 09.09 20:00-03:00 = 7s, 10.09 09:00-03:00 = 18s, 11.09 09:00-20:00 = 11s
    assert soat(d) == 36.0


def test_grafik_yoq_bolsa_oddiy_ayirma():
    d = main.working_delta(T(2026, 9, 9, 1, 0), T(2026, 9, 9, 11, 0), None, None)
    assert soat(d) == 10.0


def test_teskari_oraliq_nol():
    d = main.working_delta(T(2026, 9, 9, 11, 0), T(2026, 9, 9, 1, 0), *KUNDUZ)
    assert d == timedelta(0)


def test_hhmm_oqiladi():
    assert main._parse_hhmm("09:00") == (9, 0)
    assert main._parse_hhmm(" 3.05 ") == (3, 5)
    assert main._parse_hhmm("25:00") is None
    assert main._parse_hhmm("") is None
    assert main._parse_hhmm("nima") is None


def test_filial_grafigi_umumiydan_ustun(monkeypatch):
    class B:
        work_from = "10:00"
        work_to = "22:00"
    assert main.branch_work_hours(B()) == ((10, 0), (22, 0))

    class Bosh:
        work_from = ""
        work_to = ""
    monkeypatch.setattr(main, "WORK_HOURS", "08:00-23:00")
    assert main.branch_work_hours(Bosh()) == ((8, 0), (23, 0))

    monkeypatch.setattr(main, "WORK_HOURS", "buzuq")
    assert main.branch_work_hours(Bosh()) == (None, None)
