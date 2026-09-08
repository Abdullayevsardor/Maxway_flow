"""iiko kalitlarini env'dan o'qish.

Sabab: Railway'ga o'zgaruvchi qo'shayotganda butun qator qiymat sifatida
nusxalanib ketdi (`MAXWAY_IIKO_LOGIN = 68a4...`) va iiko «Login MAXWAY_IIKO_LOGIN
= 68a4... is not authorized» deb javob berdi — sababini topish qiyin bo'ldi.
"""
import pytest

from app import iiko


KEY = "68a4476183ce41de91aba6b53eac2824"
SECRET = "O6INbuNV7XfJ8yRC4W1-_OE8LTpBm0TR6y61TFZ1qWI="


@pytest.mark.parametrize("kiritilgan,kutilgan", [
    (KEY, KEY),                                  # to'g'ri qiymat o'zgarmaydi
    (f"MAXWAY_IIKO_LOGIN = {KEY}", KEY),         # butun qator nusxalangan
    (f"MAXWAY_IIKO_LOGIN={KEY}", KEY),           # bo'shliqsiz
    (f'  "{KEY}"  ', KEY),                       # qo'shtirnoq va bo'shliqlar
    ("", ""),
])
def test_kalit_tozalanadi(kiritilgan, kutilgan):
    assert iiko._clean_value(kiritilgan) == kutilgan


def test_client_secret_oxiridagi_tenglik_saqlanadi():
    """clientSecret base64 — oxirida «=» bo'ladi, u kesilmasligi kerak."""
    assert iiko._clean_value(SECRET) == SECRET
    assert iiko._clean_value(f"MAXWAY_IIKO_CLIENT_SECRET={SECRET}") == SECRET


def test_env_fayldan_ustun_turadi(monkeypatch):
    monkeypatch.setenv("MAXWAY_IIKO_LOGIN", f"MAXWAY_IIKO_LOGIN = {KEY}")
    monkeypatch.setenv("MAXWAY_IIKO_APP_ID", "41b2c656-e097-4c55-bf1e-5afead0df477")
    monkeypatch.setenv("MAXWAY_IIKO_CLIENT_SECRET", SECRET)
    creds = iiko.get_credentials()
    assert creds["api_key"] == KEY
    assert creds["app_id"] == "41b2c656-e097-4c55-bf1e-5afead0df477"
    assert creds["client_secret"] == SECRET
