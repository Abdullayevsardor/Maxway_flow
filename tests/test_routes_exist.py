"""Shablonlardagi forma manzillari haqiqatan route sifatida ro'yxatda bormi.

Sabab: `@app.post("/admin/categories/create")` dekoratori tasodifan o'chib
ketgan edi — funksiya oldingi route'ning `return` iga yopishib qolgan, FastAPI
uni umuman ko'rmagan va «Добавить категорию» tugmasi jim 404 qaytargan.
Sintaksis xatosi yo'q, testlar ham o'tardi — shuning uchun alohida tekshiruv.
"""
import os
import re

import main

TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "templates")


def _registered_paths() -> set:
    return {getattr(r, "path", "") for r in main.app.routes}


def _static_form_actions() -> list:
    """Shablonlardagi o'zgarmas (Jinja ifodasiz) forma manzillari."""
    out = []
    for name in sorted(os.listdir(TEMPLATES)):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
            html = f.read()
        for action in re.findall(r'action="([^"]*)"', html):
            if not action or action.startswith(("http", "#", "javascript:")):
                continue
            if "{{" in action or "{%" in action:      # dinamik — bu yerda tekshirilmaydi
                continue
            out.append((name, action.split("?")[0]))
    return out


def test_forma_manzillari_route_sifatida_royxatda():
    paths = _registered_paths()
    actions = _static_form_actions()
    assert actions, "shablonlarda forma topilmadi — test noto'g'ri ishlayapti"
    yoq = sorted({f"{tpl}: {a}" for tpl, a in actions if a not in paths})
    assert not yoq, "Bu manzillar shablonda bor, lekin route yo'q:\n  " + "\n  ".join(yoq)


def test_kategoriya_qoshish_route_bor():
    """Aynan o'sha yo'qolgan route — qaytib yo'qolmasin."""
    assert "/admin/categories/create" in _registered_paths()
