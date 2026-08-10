"""MAXWAY — ishlarni saqlash va ijrochilarga yo'naltirish tizimi (FastAPI)."""
import os
import json
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, Request, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db, SessionLocal
from app import models, auth
from app.models import Role, Status, Priority

print(">>> [MAXWAY] create_all boshlandi", flush=True)
Base.metadata.create_all(bind=engine)
print(">>> [MAXWAY] create_all tugadi", flush=True)


def _ensure_columns():
    """Eski bazaga yetishmagan ustunlarни qo'shadi (SQLite + Postgres mos)."""
    from sqlalchemy import inspect as sa_inspect
    checks = [("attachments", "stage", "VARCHAR(10) DEFAULT 'request'"),
              ("requests", "subcategory_id", "INTEGER"),
              ("branches", "phone", "VARCHAR(40) DEFAULT ''"),
              ("branches", "director_name", "VARCHAR(120) DEFAULT ''"),
              ("notifications", "from_name", "VARCHAR(120)"),
              ("stop_entries", "resolved_at", "TIMESTAMP"),
              ("stop_entries", "supply_comment", "TEXT DEFAULT ''")]
    try:
        insp = sa_inspect(engine)
        tables = insp.get_table_names()
        for table, col, ddl in checks:
            if table not in tables:
                continue
            cols = [c["name"] for c in insp.get_columns(table)]
            if col not in cols:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                print(f">>> [MAXWAY] '{col}' ustuni '{table}' ga qo'shildi", flush=True)
    except Exception as e:
        print(">>> [MAXWAY] ensure_columns xato:", e, flush=True)


print(">>> [MAXWAY] ensure_columns boshlandi", flush=True)
_ensure_columns()
print(">>> [MAXWAY] ensure_columns tugadi", flush=True)


def _ensure_enum_values():
    """Postgres 'role' enum turiga yangi qiymatlarni (viewer) qo'shadi.
    Python enumga qiymat qo'shilsa, PG enum turi avtomatik yangilanmaydi."""
    try:
        if "postgres" not in str(engine.url):
            return  # SQLite'da enum matn sifatida — kerak emas
        from sqlalchemy import text
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            row = conn.execute(text(
                "SELECT t.typname FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid "
                "WHERE e.enumlabel='executor' LIMIT 1")).first()
            if row:
                tname = row[0]
                for val in ("viewer", "kpp"):
                    conn.execute(text(f"ALTER TYPE {tname} ADD VALUE IF NOT EXISTS '{val}'"))
                print(f">>> [MAXWAY] enum '{tname}' ga viewer/kpp qo'shildi", flush=True)
        finally:
            conn.close()
    except Exception as e:
        print(">>> [MAXWAY] enum migratsiya xato:", e, flush=True)


_ensure_enum_values()


def _auto_seed():
    """Birinchi ishga tushishда (foydalanuvchи yo'q bo'lsa) demo ma'lumot yaratadi."""
    try:
        db = SessionLocal()
        has_user = db.query(models.User).first()
        db.close()
        if not has_user:
            import seed as _seed
            _seed.seed()
            print(">>> [MAXWAY] Demo ma'lumot yaratildi (auto-seed)", flush=True)
        else:
            print(">>> [MAXWAY] Foydalanuvchи bor — seed o'tkazib yuborildi", flush=True)
    except Exception as e:
        print(">>> [MAXWAY] auto-seed xato:", e, flush=True)


print(">>> [MAXWAY] auto_seed boshlandi", flush=True)
_auto_seed()
print(">>> [MAXWAY] auto_seed tugadi — ilova yaratilmoqda", flush=True)


def _admin_tools():
    """Startupда: barcha admin emaillarini ko'rsatadi va (ADMIN_RESET berilsa) parol tiklaydi.
    ADMIN_RESET formati: "email:yangiparol"  (masalan: a.ruzikulov@gmail.com:12345678)"""
    try:
        db = SessionLocal()
        # eski "На проверке" (on_check) zayavkalarni "В работе" (in_progress) ga o'tkazamiz
        try:
            n1 = db.query(models.Request).filter(models.Request.status == models.Status.on_check)\
                .update({models.Request.status: models.Status.in_progress}, synchronize_session=False)
            n2 = db.query(models.StatusHistory).filter(models.StatusHistory.status == models.Status.on_check)\
                .update({models.StatusHistory.status: models.Status.in_progress}, synchronize_session=False)
            if n1 or n2:
                db.commit()
                print(f">>> [MAXWAY] on_check ko'chirildi: zayavka={n1}, tarix={n2}", flush=True)
        except Exception as e:
            db.rollback()
            print(">>> [MAXWAY] on_check migratsiya xato:", e, flush=True)
        admins = db.query(models.User).filter(models.User.role == models.Role.admin).all()
        print(">>> [MAXWAY] Adminlar:", flush=True)
        for a in admins:
            print(f"      - {a.email}  (active={a.is_active})", flush=True)
        reset = os.environ.get("ADMIN_RESET", "").strip()
        if reset and ":" in reset:
            em, pw = reset.split(":", 1)
            em = em.lower().strip()
            u = db.query(models.User).filter(models.User.email == em).first()
            if u:
                u.hashed_password = auth.hash_password(pw)
                u.is_active = True
                db.commit()
                print(f">>> [MAXWAY] ✅ Parol tiklandi: {em}", flush=True)
            else:
                print(f">>> [MAXWAY] ⚠ ADMIN_RESET: '{em}' topilmadi", flush=True)
        db.close()
    except Exception as e:
        print(">>> [MAXWAY] admin_tools xato:", e, flush=True)


_admin_tools()

app = FastAPI(title="MAXWAY")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    """Sahifalar keshda saqlanmasin (eski qiymatlar ko'rinmasin). Statika keshlanaveradi."""
    response = await call_next(request)
    if not request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
templates = Jinja2Templates(directory="templates")
print(">>> [MAXWAY] ilova tayyor ✅", flush=True)

STATUS_LABELS = {
    "new": "Новая", "approved": "Одобрена", "in_progress": "В работе",
    "done": "Выполнена", "rejected": "Отклонена",
}
PRIORITY_LABELS = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
ROLE_LABELS = {"admin": "АДМИН", "manager": "МЕНЕДЖЕР", "executor": "ИСПОЛНИТЕЛЬ", "client": "ЗАКАЗЧИК", "viewer": "ПРОСМОТР", "kpp": "КПП"}
# Stop-list sabablari
REASON_LABELS = {
    "sales_growth": "Рост продаж",
    "wrong_forecast": "Неправильный прогноз продаж",
    "supplier_late": "Поставщик опоздал",
    "supplier_stop": "На стопе у поставщика",
    "branch_no_order": "Не заказал филиал",
    "tech_problem": "Технический проблема",
}

templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS, PRIORITY_LABELS=PRIORITY_LABELS,
    ROLE_LABELS=ROLE_LABELS, REASON_LABELS=REASON_LABELS, APP_NAME="MAXWAY", now=datetime.utcnow,
)


def current_user(request: Request, db: Session):
    return auth.get_current_user_optional(request, db)


# ---------- Telegram bot ----------
def get_bot_token() -> str:
    """Token: MAXWAY_BOT_TOKEN env yoki telegram_token.txt fayldan."""
    tok = os.environ.get("MAXWAY_BOT_TOKEN", "").strip()
    if not tok:
        try:
            with open("telegram_token.txt", encoding="utf-8") as f:
                tok = f.read().strip()
        except FileNotFoundError:
            tok = ""
    # Agar "MAXWAY_BOT_TOKEN=xxx" ko'rinishida yozilgan bo'lsa, faqat qiymatini olamiz
    if "=" in tok:
        tok = tok.split("=", 1)[1].strip()
    return tok


def get_app_url() -> str:
    """Loyiha manzili: MAXWAY_URL env yoki maxway_url.txt, aks holда localhost."""
    u = os.environ.get("MAXWAY_URL", "").strip()
    if not u:
        try:
            with open("maxway_url.txt", encoding="utf-8") as f:
                u = f.read().strip()
        except FileNotFoundError:
            u = ""
    return u or "http://127.0.0.1:8000"


def send_telegram(chat_id: str, text: str, button_url: str = "",
                  button_text: str = "Открыть MAXWAY"):
    """Telegramга xabar yuboradi (ixtiyoriy tugma bilan). Xatolik tinch o'tadi."""
    token = get_bot_token()
    if not token or not chat_id:
        return
    try:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if button_url:
            params["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": button_text, "url": button_url}]]})
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(params).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=8)
    except Exception:
        pass


def base_requests(db: Session, user):
    """Klient → o'z filiali; bo'limga biriktirilgan admin/menejer/ijrochi → faqat o'z bo'limi;
    bo'limsiz admin (категория = —) → barcha zayavkalar (bosh admin)."""
    q = db.query(models.Request)
    if user.role == Role.client:
        q = q.filter(models.Request.branch_id == user.user_branch_id)
    elif user.role == Role.kpp:
        ids = [b.id for b in user.visible_branches]
        q = q.filter(models.Request.branch_id.in_(ids if ids else [-1]))
    elif user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
        q = q.filter(models.Request.department_id == user.department_id)
    return q


def scoped_executors(db: Session, user):
    """Biriktirish uchun ijrochilar: bo'limga biriktirilgan admin/menejer faqat
    o'z bo'limidagi ijrochilarni ko'radi; bo'limsiz admin — hammasini."""
    q = db.query(models.User).filter(models.User.is_active == True)
    if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
        q = q.filter(models.User.department_id == user.department_id)
    return q.all()


def scoped_departments(db: Session, user):
    """Bo'limga biriktirilgan admin/ijrochi faqat o'z bo'limini ko'radi."""
    q = db.query(models.Department)
    if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
        q = q.filter(models.Department.id == user.department_id)
    return q.all()


def display_name(u):
    """Filial (client) bo'lsa — direktor ismi, aks holda full_name."""
    if u and u.role == Role.client and u.branch and u.branch.director_name:
        return u.branch.director_name
    return u.full_name if u else "—"


def add_history(db: Session, req: models.Request, status: models.Status, note=""):
    db.add(models.StatusHistory(request_id=req.id, status=status, note=note))


# ===================== AUTH =====================
@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse("/dashboard" if current_user(request, db) else "/login", 302)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/dashboard", 302)
    return templates.TemplateResponse(request, "login.html", {"request": request})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                 db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, "login.html",
            {"request": request, "error": "Неверный email или пароль"}, status_code=401)
    token = auth.create_access_token(user.id)
    resp = RedirectResponse("/dashboard", 302)
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, max_age=7200)
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    deps = db.query(models.Department).all()
    return templates.TemplateResponse(request, "register.html",
        {"request": request, "departments": deps})


@app.post("/register")
def register_submit(request: Request, full_name: str = Form(...), email: str = Form(...),
                    password: str = Form(...), department_id: Optional[int] = Form(None),
                    db: Session = Depends(get_db)):
    email = email.lower().strip()
    if db.query(models.User).filter(models.User.email == email).first():
        deps = db.query(models.Department).all()
        return templates.TemplateResponse(request, "register.html",
            {"request": request, "departments": deps,
             "error": "Bu email allaqachon ro'yxatdan o'tgan"}, status_code=400)
    user = models.User(full_name=full_name.strip(), email=email,
                       hashed_password=auth.hash_password(password),
                       role=Role.executor, department_id=department_id)
    db.add(user); db.commit(); db.refresh(user)
    token = auth.create_access_token(user.id)
    resp = RedirectResponse("/dashboard", 302)
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, max_age=7200)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", 302)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ===================== DASHBOARD =====================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    q = base_requests(db, user)
    from sqlalchemy import func as _func
    # har bo'lim bo'yicha foydalanuvchining o'z zayavkalari soni
    dep_counts = dict(q.with_entities(models.Request.department_id, _func.count(models.Request.id))
                      .group_by(models.Request.department_id).all())
    ctx = {
        "request": request, "user": user, "active": "dashboard",
        "total": q.count(),
        "new": q.filter(models.Request.status == Status.new).count(),
        "in_progress": q.filter(models.Request.status == Status.in_progress).count(),
        "done": q.filter(models.Request.status == Status.done).count(),
        "unassigned": q.filter(~models.Request.assignees.any(),
                               ~models.Request.status.in_([Status.done, Status.rejected])).count(),
        "departments": scoped_departments(db, user),
        "dep_counts": dep_counts,
        "recent": q.order_by(models.Request.created_at.desc()).limit(10).all(),
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


# ===================== ZAYAVKALAR =====================
@app.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request, department_id: Optional[int] = None,
                  status: Optional[str] = None, q: Optional[str] = None,
                  db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    query = base_requests(db, user)
    if department_id:
        query = query.filter(models.Request.department_id == department_id)
    if status == "overdue":
        query = query.filter(models.Request.deadline.isnot(None),
                             models.Request.deadline < datetime.utcnow(),
                             models.Request.status.notin_([Status.done, Status.rejected]))
    elif status in STATUS_LABELS:
        query = query.filter(models.Request.status == status)
    if q:
        query = query.filter(models.Request.title.ilike(f"%{q}%"))
    items = query.order_by(models.Request.created_at.desc()).all()

    base = base_requests(db, user)
    counts = {
        "all": base.count(),
        "new": base.filter(models.Request.status == Status.new).count(),
        "approved": base.filter(models.Request.status == Status.approved).count(),
        "in_progress": base.filter(models.Request.status == Status.in_progress).count(),
        "on_check": base.filter(models.Request.status == Status.on_check).count(),
        "done": base.filter(models.Request.status == Status.done).count(),
        "rejected": base.filter(models.Request.status == Status.rejected).count(),
        "overdue": base.filter(models.Request.deadline.isnot(None),
                              models.Request.deadline < datetime.utcnow(),
                              models.Request.status.notin_([Status.done, Status.rejected])).count(),
    }
    selected_dep = db.get(models.Department, department_id) if department_id else None
    subcats = db.query(models.Subcategory).order_by(models.Subcategory.name).all()
    subcats_map = {}
    for s in subcats:
        subcats_map.setdefault(s.department_id, []).append({"id": s.id, "name": s.name})
    return templates.TemplateResponse(request, "requests.html", {
        "request": request, "user": user, "active": "requests",
        "items": items, "departments": scoped_departments(db, user),
        "executors": scoped_executors(db, user), "selected_dep": selected_dep,
        "selected_status": status, "counts": counts, "search": q or "",
        "branches": db.query(models.Branch).order_by(models.Branch.name).all(),
        "subcats_map": subcats_map,
    })


@app.get("/requests/{req_id}", response_class=HTMLResponse)
def request_detail(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if not r:
        raise HTTPException(404, "Заявка не найдена")
    if user.role == Role.client and r.branch_id != user.user_branch_id:
        return RedirectResponse("/requests", 302)
    # bo'limga biriktirilgan admin/menejer/ijrochi boshqa bo'lim zayavkasini ko'rolmaydi
    if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id \
            and r.department_id != user.department_id:
        return RedirectResponse("/requests", 302)
    return templates.TemplateResponse(request, "request_detail.html", {
        "request": request, "user": user, "active": "requests", "r": r,
        "executors": scoped_executors(db, user),
    })


@app.post("/requests/create")
def create_request(request: Request, title: str = Form(...), description: str = Form(""),
                   department_id: int = Form(...), subcategory_id: Optional[int] = Form(None),
                   priority: str = Form("medium"),
                   customer_name: str = Form(""), customer_email: str = Form(""),
                   customer_phone: str = Form(""), branch_id: Optional[int] = Form(None),
                   deadline: str = Form(""), photos: List[UploadFile] = File([]),
                   videos: List[UploadFile] = File([]), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role in (Role.executor, Role.viewer, Role.kpp):
        return RedirectResponse("/requests", 302)
    if not title.strip():
        return RedirectResponse("/requests?err=title", 302)
    dl = None
    if deadline:
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dl = datetime.strptime(deadline, fmt)
                break
            except ValueError:
                dl = None
    branch_name = ""
    branch_phone = ""
    branch_director = ""
    if user.role == Role.client and user.user_branch_id:
        branch_id = user.user_branch_id
    if branch_id:
        b = db.get(models.Branch, branch_id)
        if b:
            branch_name = b.name
            branch_phone = b.phone or ""
            branch_director = b.director_name or ""
    # Заказчик: filial bo'lsa — direktor ismi; boshqalar — profil ismi
    if user.role == Role.client:
        cust_name = customer_name.strip() or branch_director or user.full_name or branch_name
        cust_phone = customer_phone.strip() or branch_phone or (user.phone or "")
    else:
        cust_name = customer_name.strip() or user.full_name
        cust_phone = customer_phone.strip() or (user.phone or "")
    cust_email = customer_email.strip() or user.email
    r = models.Request(title=title.strip(), description=description.strip(),
                       department_id=department_id,
                       subcategory_id=subcategory_id or None,
                       priority=Priority(priority),
                       status=Status.new, created_by=user.id,
                       customer_name=cust_name, customer_email=cust_email,
                       customer_phone=cust_phone, branch=branch_name,
                       branch_id=branch_id, deadline=dl)
    db.add(r); db.flush()
    add_history(db, r, Status.new, "Заявка создана")

    img_ext = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    vid_ext = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp")
    os.makedirs("static/uploads/requests", exist_ok=True)
    idx = 0
    for up in list(photos) + list(videos):
        if not up or not up.filename:
            continue
        ext = os.path.splitext(up.filename)[1].lower()
        if ext in img_ext:
            kind = "image"
        elif ext in vid_ext:
            kind = "video"
        else:
            continue
        fname = f"req_{r.id}_{idx}{ext}"
        idx += 1
        with open(os.path.join("static", "uploads", "requests", fname), "wb") as fh:
            fh.write(up.file.read())
        db.add(models.Attachment(request_id=r.id,
                                 file_path=f"/static/uploads/requests/{fname}", kind=kind))
    db.commit()
    notify_category(db, r)
    return RedirectResponse(f"/requests/{r.id}", 302)


def notify_category(db: Session, r: models.Request):
    """Zayavка kategoriyasidagi xodimlarга va adminларга bildirishnoma (sayt + Telegram)."""
    dep = r.department
    recipients = db.query(models.User).filter(
        models.User.is_active == True,
        models.User.id != r.created_by,
        models.User.role.in_([Role.executor, Role.manager, Role.admin, Role.viewer]),
        ((models.User.department_id == r.department_id)
         | ((models.User.role == Role.admin) & (models.User.department_id.is_(None)))
         | (models.User.role == Role.viewer))
    ).all()
    seen = set()
    link = f"/requests/{r.id}"
    tg_text = (f"🔔 <b>Новая заявка — MAXWAY</b>\n\n"
               f"📌 <b>{r.title}</b>\n"
               f"🏷 Категория: {dep.name if dep else '—'}\n"
               f"⚡️ Приоритет: {PRIORITY_LABELS.get(r.priority.value)}\n"
               f"🏢 Филиал: {r.branch_obj.name if r.branch_obj else (r.branch or '—')}\n"
               f"👤 Заказчик: {r.customer_name or '—'}\n"
               f"📞 Телефон: {r.customer_phone or '—'}\n"
               f"⏰ Дедлайн: {r.deadline.strftime('%d.%m.%Y') if r.deadline else '—'}")
    site_text = f"Новая заявка «{r.title}» — {dep.name if dep else 'без категории'}"
    for u in recipients:
        if u.id in seen:
            continue
        seen.add(u.id)
        db.add(models.Notification(user_id=u.id, text=site_text, link=link,
                                   from_name=r.customer_name or "—"))
        if u.telegram_chat_id:
            send_telegram(u.telegram_chat_id, tg_text,
                          button_url=f"{get_app_url()}{link}")
    db.commit()


@app.get("/api/notifications")
def api_notifications(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"unread": 0, "items": []})
    items = db.query(models.Notification).filter(models.Notification.user_id == user.id)\
        .order_by(models.Notification.created_at.desc()).limit(50).all()
    # bo'limga biriktirilgan foydalanuvchi faqat o'z bo'limi zayavkalariga oid xabarlarni ko'radi
    if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
        kept = []
        for n in items:
            ok = True
            if n.link and n.link.startswith("/requests/"):
                try:
                    rid = int(n.link.rsplit("/", 1)[1])
                    req = db.get(models.Request, rid)
                    if req and req.department_id != user.department_id:
                        ok = False
                except (ValueError, IndexError):
                    pass
            if ok:
                kept.append(n)
        items = kept[:20]
    else:
        items = items[:20]
    unread = sum(1 for n in items if not n.is_read)
    return JSONResponse({
        "unread": unread,
        "items": [{"text": n.text, "link": n.link, "is_read": n.is_read,
                   "from_name": n.from_name or "",
                   "time": n.created_at.strftime("%d.%m %H:%M")} for n in items]
    })


@app.post("/api/notifications/read")
def api_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        db.query(models.Notification).filter(
            models.Notification.user_id == user.id,
            models.Notification.is_read == False).update({models.Notification.is_read: True})
        db.commit()
    return JSONResponse({"ok": True})


@app.post("/requests/{req_id}/assign")
def assign_request(req_id: int, request: Request, assigned_to: int = Form(...),
                   db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r:
        # bo'limga biriktirilgan admin/menejer faqat o'z bo'limida ish qiladi
        if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
            if r.department_id != user.department_id:
                return RedirectResponse("/requests", 302)
            assignee_chk = db.get(models.User, assigned_to)
            if not assignee_chk or assignee_chk.department_id != user.department_id:
                return RedirectResponse(f"/requests/{req_id}", 302)
        assignee = db.get(models.User, assigned_to)
        if not assignee:
            return RedirectResponse(f"/requests/{req_id}", 302)
        # ro'yxatga qo'shamiz (avvalgilarni almashtirmaymiz)
        if assignee not in r.assignees:
            r.assignees.append(assignee)
        r.assigned_to = assigned_to   # legacy: oxirgi biriktirilgan
        # statusni majburan o'zgartirmaymiz — ijrochi o'zi: Одобрить → Начать работу
        if r.status == Status.rejected:
            r.status = Status.new
        add_history(db, r, r.status, f"Исполнитель назначен: {assignee.full_name}")
        db.commit()
        # Telegram xabari (ijrochining chat_id si bo'lsa)
        if assignee.telegram_chat_id:
            br = r.branch_obj.name if r.branch_obj else (r.branch or "—")
            text = (f"🔔 <b>Новое назначение — MAXWAY</b>\n\n"
                    f"📌 <b>{r.title}</b>\n"
                    f"🏷 Исполнитель: {assignee.full_name}\n"
                    f"⚡️ Приоритет: {PRIORITY_LABELS.get(r.priority.value)}\n"
                    f"🏢 Филиал: {br}\n"
                    f"👤 Заказчик: {r.customer_name or '—'}\n"
                    f"📞 Телефон: {r.customer_phone or '—'}\n"
                    f"⏰ Дедлайн: {r.deadline.strftime('%d.%m.%Y') if r.deadline else '—'}")
            send_telegram(assignee.telegram_chat_id, text,
                          button_url=f"{get_app_url()}/requests/{r.id}")
    return RedirectResponse(f"/requests/{req_id}", 302)


@app.post("/requests/{req_id}/unassign/{uid}")
def unassign_request(req_id: int, uid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    p = db.get(models.User, uid)
    if r and p and p in r.assignees:
        r.assignees.remove(p)
        # legacy assigned_to ni yangilaymiz
        r.assigned_to = r.assignees[-1].id if r.assignees else None
        add_history(db, r, r.status, f"Исполнитель снят: {p.full_name}")
        db.commit()
    return RedirectResponse(f"/requests/{req_id}", 302)


@app.post("/requests/{req_id}/reject")
def reject_request(req_id: int, request: Request, reason: str = Form(""),
                   db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r:
        r.status = Status.rejected
        r.reject_reason = reason.strip()
        add_history(db, r, Status.rejected, reason.strip()[:200])
        db.commit()
    return RedirectResponse(f"/requests/{req_id}", 302)


@app.post("/requests/{req_id}/delete")
def delete_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """Заявкани butunlay o'chiradi — admin yoki menejer."""
    user = current_user(request, db)
    if not user or user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r:
        # diskдаги fayllarни ham o'chiramiz
        for att in r.attachments:
            try:
                fp = att.file_path.lstrip("/")
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass
        # shu zayavkaga tegishli bildirishnomalarni o'chiramiz (link orqali bog'langan)
        db.query(models.Notification).filter(
            models.Notification.link == f"/requests/{req_id}").delete(synchronize_session=False)
        db.delete(r)   # comments/history/attachments cascade bilan o'chadi
        db.commit()
    return RedirectResponse("/requests", 302)


@app.post("/requests/{req_id}/status")
def change_status(req_id: int, request: Request, status: str = Form(...),
                  db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r and status in STATUS_LABELS:
        notes = {
            "new": "Статус изменён",
            "approved": "Одобрено исполнителем",
            "in_progress": "Работа начата",
            "on_check": "Отправлено на проверку",
            "done": "Работа завершена",
            "rejected": "Отклонено",
        }
        r.status = Status(status)
        # ijrochi ishni boshlasa va hali biriktirilmagan bo'lsa — o'zi ro'yxatga qo'shiladi
        if user.role == Role.executor and not r.assignees \
                and status in ("approved", "in_progress", "on_check", "done"):
            r.assignees.append(user)
            r.assigned_to = user.id
        add_history(db, r, Status(status), notes.get(status, "Статус изменён"))
        db.commit()
    ref = request.headers.get("referer", f"/requests/{req_id}")
    return RedirectResponse(ref, 302)


@app.post("/requests/{req_id}/comment")
def add_comment(req_id: int, request: Request, text: str = Form(...),
                db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role in (Role.viewer, Role.kpp):
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r and text.strip():
        db.add(models.Comment(request_id=req_id, user_id=user.id, text=text.strip()))
        db.commit()
        # zayavка egasiga bildirishnoma (boshqa odam izoh yozsa)
        if r.created_by and r.created_by != user.id:
            link = f"/requests/{r.id}"
            db.add(models.Notification(user_id=r.created_by,
                   text=f"Новый комментарий к «{r.title}»: {text.strip()[:60]}", link=link,
                   from_name=display_name(user)))
            db.commit()
            creator = db.get(models.User, r.created_by)
            if creator and creator.telegram_chat_id:
                send_telegram(creator.telegram_chat_id,
                    f"💬 <b>Новый комментарий — MAXWAY</b>\n\n"
                    f"📌 <b>{r.title}</b>\n"
                    f"👤 {user.full_name}:\n{text.strip()}",
                    button_url=f"{get_app_url()}{link}")
    return RedirectResponse(f"/requests/{req_id}", 302)


@app.post("/requests/{req_id}/solution")
def add_solution(req_id: int, request: Request, comment: str = Form(""),
                 photos: List[UploadFile] = File([]), videos: List[UploadFile] = File([]),
                 db: Session = Depends(get_db)):
    """Ijrochи yechimни (rasm/video/izoh) biriktiradi."""
    user = current_user(request, db)
    if not user or user.role == Role.client:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if not r:
        return RedirectResponse("/requests", 302)
    img_ext = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    vid_ext = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp")
    os.makedirs("static/uploads/requests", exist_ok=True)
    idx = db.query(models.Attachment).filter(models.Attachment.request_id == r.id).count()
    for up in list(photos) + list(videos):
        if not up or not up.filename:
            continue
        ext = os.path.splitext(up.filename)[1].lower()
        kind = "image" if ext in img_ext else ("video" if ext in vid_ext else None)
        if not kind:
            continue
        fname = f"req_{r.id}_sol_{idx}{ext}"
        idx += 1
        with open(os.path.join("static", "uploads", "requests", fname), "wb") as fh:
            fh.write(up.file.read())
        db.add(models.Attachment(request_id=r.id,
               file_path=f"/static/uploads/requests/{fname}", kind=kind, stage="solution"))
    if comment.strip():
        db.add(models.Comment(request_id=r.id, user_id=user.id,
               text="✅ Решение: " + comment.strip()))
    # yechim yuborilgach — ish yakunlandi
    if r.status not in (Status.done, Status.rejected):
        r.status = Status.done
        add_history(db, r, Status.done, "Работа завершена")
    db.commit()
    # zayavка egasiga (klиентга) bildirishnoma
    if r.created_by and r.created_by != user.id:
        link = f"/requests/{r.id}"
        db.add(models.Notification(user_id=r.created_by,
               text=f"Добавлено решение по заявке «{r.title}»", link=link,
               from_name=display_name(user)))
        db.commit()
        creator = db.get(models.User, r.created_by)
        if creator and creator.telegram_chat_id:
            send_telegram(creator.telegram_chat_id,
                f"✅ <b>Решение добавлено — MAXWAY</b>\n\n📌 <b>{r.title}</b>\n"
                f"👤 {user.full_name}" + (f"\n💬 {comment.strip()}" if comment.strip() else ""),
                button_url=f"{get_app_url()}{link}")
    return RedirectResponse(f"/requests/{req_id}", 302)


@app.post("/comments/{cid}/delete")
def delete_comment(cid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    c = db.get(models.Comment, cid)
    if c and (user.role in (Role.admin, Role.manager) or c.user_id == user.id):
        rid = c.request_id
        db.delete(c); db.commit()
        return RedirectResponse(f"/requests/{rid}", 302)
    return RedirectResponse("/requests", 302)


# ===================== PROFIL =====================
@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    return templates.TemplateResponse(request, "profile.html",
        {"request": request, "user": user, "active": "profile", "saved": False})


@app.post("/profile/update")
def profile_update(request: Request, full_name: str = Form(...), phone: str = Form(""),
                   bio: str = Form(""), telegram_chat_id: str = Form(""),
                   email: str = Form(""),
                   current_password: str = Form(""),
                   new_password: str = Form(""), confirm_password: str = Form(""),
                   photo: UploadFile = File(None), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    # filial (client) bo'lsa — ism/telefon filial direktoriga yoziladi (filial nomi o'zgarmaydi)
    if user.role == Role.client and user.user_branch_id:
        b = db.get(models.Branch, user.user_branch_id)
        if b:
            b.director_name = full_name.strip()
            b.phone = phone.strip()
    else:
        user.full_name = full_name.strip()
        user.phone = phone.strip()
        # email (login) o'zgartirish — band bo'lmasa
        new_email = email.lower().strip()
        if new_email and new_email != user.email:
            taken = db.query(models.User).filter(
                models.User.email == new_email, models.User.id != user.id).first()
            if not taken:
                user.email = new_email
    user.bio = bio.strip()
    user.telegram_chat_id = telegram_chat_id.strip() or None
    # rasm yuklash
    if photo is not None and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            os.makedirs("static/uploads", exist_ok=True)
            fname = f"avatar_{user.id}{ext}"
            with open(os.path.join("static", "uploads", fname), "wb") as f:
                f.write(photo.file.read())
            user.avatar = f"/static/uploads/{fname}"
    # parol o'zgartirish (yangi == tasdiq va joriy to'g'ri bo'lsa)
    msg = None
    if new_password:
        if new_password != confirm_password:
            msg = "Новые пароли не совпадают"
        elif not auth.verify_password(current_password, user.hashed_password):
            msg = "Текущий пароль неверный"
        else:
            user.hashed_password = auth.hash_password(new_password)
    db.commit()
    return templates.TemplateResponse(request, "profile.html",
        {"request": request, "user": user, "active": "profile",
         "saved": True, "msg": msg})


# ===================== IJROCHILAR =====================
@app.get("/executors", response_class=HTMLResponse)
def executors_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    people_q = db.query(models.User)
    # bo'limga biriktirilgan admin/ijrochi faqat o'z bo'limidagilarni ko'radi
    if user.role in (Role.admin, Role.manager, Role.executor) and user.department_id:
        people_q = people_q.filter(models.User.department_id == user.department_id)
    people = people_q.order_by(models.User.full_name).all()
    stats = {}
    for p in people:
        rq = db.query(models.Request).filter(models.Request.assignees.any(models.User.id == p.id))
        stats[p.id] = {
            "total": rq.count(),
            "in_progress": rq.filter(models.Request.status == Status.in_progress).count(),
            "done": rq.filter(models.Request.status == Status.done).count(),
        }
    return templates.TemplateResponse(request, "executors.html",
        {"request": request, "user": user, "active": "executors",
         "people": people, "stats": stats})


@app.post("/executors/{uid}/toggle")
def toggle_executor(uid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/executors", 302)
    p = db.get(models.User, uid)
    if p:
        p.is_active = not p.is_active
        db.commit()
    return RedirectResponse("/executors", 302)


@app.post("/executors/create")
def create_executor(request: Request, full_name: str = Form(...), email: str = Form(...),
                    password: str = Form("12345678"), position: str = Form(""),
                    specialization: str = Form(""), phone: str = Form(""),
                    db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/executors", 302)
    email = email.lower().strip()
    if not db.query(models.User).filter(models.User.email == email).first():
        db.add(models.User(full_name=full_name.strip(), email=email,
                           hashed_password=auth.hash_password(password or "12345678"),
                           role=Role.executor, position=position.strip(),
                           specialization=specialization.strip(), phone=phone.strip(),
                           department_id=user.department_id, is_active=True))
        db.commit()
    return RedirectResponse("/executors", 302)


@app.post("/executors/{uid}/delete")
def delete_executor(uid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/executors", 302)
    p = db.get(models.User, uid)
    if p and p.id != user.id:
        db.query(models.Request).filter(models.Request.assigned_to == uid)\
            .update({models.Request.assigned_to: None})
        db.delete(p); db.commit()
    return RedirectResponse("/executors", 302)


@app.post("/executors/{uid}/edit")
def edit_executor(uid: int, request: Request, full_name: str = Form(...),
                  position: str = Form(""), specialization: str = Form(""),
                  phone: str = Form(""), schedule: str = Form(""),
                  experience: str = Form(""), telegram: str = Form(""),
                  db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role not in (Role.admin, Role.manager):
        return RedirectResponse("/executors", 302)
    p = db.get(models.User, uid)
    if p:
        p.full_name = full_name.strip()
        p.position = position.strip()
        p.specialization = specialization.strip()
        p.phone = phone.strip()
        p.schedule = schedule.strip()
        p.experience = experience.strip()
        p.telegram = telegram.strip()
        db.commit()
    return RedirectResponse("/executors", 302)


# ===================== ANALITIKA =====================
@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role not in (Role.admin, Role.viewer):
        return RedirectResponse("/dashboard", 302)
    base = db.query(models.Request)
    total = base.count()
    status_stats = {s: base.filter(models.Request.status == s).count() for s in Status}
    done = status_stats[Status.done]
    sla = round(done / total * 100) if total else 0
    overdue = base.filter(models.Request.deadline.isnot(None),
                         models.Request.deadline < datetime.utcnow(),
                         models.Request.status.notin_([Status.done, Status.rejected])).count()
    dep_stats = (db.query(models.Department.name, models.Department.color,
                          func.count(models.Request.id))
                 .outerjoin(models.Request).group_by(models.Department.id).all())
    max_count = max([row[2] for row in dep_stats], default=1) or 1
    # ijrochilar samaradorligi
    execs = db.query(models.User).filter(models.User.is_active == True).all()
    exec_stats = []
    for e in execs:
        rq = db.query(models.Request).filter(models.Request.assignees.any(models.User.id == e.id))
        t = rq.count()
        d = rq.filter(models.Request.status == Status.done).count()
        if t:
            exec_stats.append({"name": e.full_name, "email": e.email, "total": t,
                               "done": d, "pct": round(d / t * 100)})
    return templates.TemplateResponse(request, "analytics.html", {
        "request": request, "user": user, "active": "analytics",
        "total": total, "sla": sla, "overdue": overdue,
        "status_stats": {s.value: status_stats[s] for s in Status},
        "dep_stats": dep_stats, "max_count": max_count, "exec_stats": exec_stats,
    })


# ===================== BO'LIMLAR =====================
@app.get("/departments", response_class=HTMLResponse)
def departments_page(request: Request, error: Optional[str] = None,
                     db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    return templates.TemplateResponse(request, "departments.html",
        {"request": request, "user": user, "active": "departments",
         "departments": db.query(models.Department).all(), "error": error})


@app.post("/departments/create")
def departments_create(request: Request, name: str = Form(...), icon: str = Form("🗂️"),
                       color: str = Form("#2563eb"), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if db.query(models.Department).count() >= 10:
        return RedirectResponse("/departments?error=limit", 302)
    db.add(models.Department(name=name.strip(), icon=(icon.strip() or "🗂️"), color=color))
    db.commit()
    return RedirectResponse("/departments", 302)


@app.post("/departments/{dep_id}/delete")
def departments_delete(dep_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    d = db.get(models.Department, dep_id)
    if d:
        db.query(models.User).filter(models.User.department_id == dep_id)\
            .update({models.User.department_id: None}, synchronize_session=False)
        for r in db.query(models.Request).filter(models.Request.department_id == dep_id).all():
            db.query(models.Notification).filter(
                models.Notification.link == f"/requests/{r.id}").delete(synchronize_session=False)
            db.delete(r)
        db.delete(d); db.commit()
    return RedirectResponse("/departments", 302)


# ===================== ADMIN PANEL =====================
@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role != Role.admin:
        return RedirectResponse("/dashboard", 302)
    from sqlalchemy import func as _func
    req_counts = dict(db.query(models.Request.created_by, _func.count(models.Request.id))
                      .group_by(models.Request.created_by).all())
    # har filialning login (client) emaili — tahrirlashda ko'rsatish uchun
    branch_logins = dict(db.query(models.User.user_branch_id, models.User.email)
                         .filter(models.User.role == Role.client,
                                 models.User.user_branch_id.isnot(None)).all())
    return templates.TemplateResponse(request, "admin.html", {
        "request": request, "user": user, "active": "admin",
        "users": db.query(models.User).order_by(models.User.full_name).all(),
        "departments": db.query(models.Department).all(),
        "branches": db.query(models.Branch).order_by(models.Branch.name).all(),
        "req_counts": req_counts, "branch_logins": branch_logins,
    })


@app.post("/admin/users/create")
def admin_user_create(request: Request, full_name: str = Form(...), email: str = Form(...),
                      password: str = Form("12345678"), role: str = Form("executor"),
                      department_id: Optional[int] = Form(None), phone: str = Form(""),
                      telegram_chat_id: str = Form(""), kpp_branch_ids: List[int] = Form([]),
                      db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    email = email.lower().strip()
    if not db.query(models.User).filter(models.User.email == email).first():
        nu = models.User(full_name=full_name.strip(), email=email,
                         hashed_password=auth.hash_password(password or "12345678"),
                         role=Role(role), department_id=department_id,
                         phone=phone.strip(), telegram_chat_id=telegram_chat_id.strip(),
                         is_active=True)
        if role == "kpp" and kpp_branch_ids:
            nu.visible_branches = db.query(models.Branch).filter(
                models.Branch.id.in_(kpp_branch_ids)).all()
        db.add(nu)
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/users/{uid}/delete")
def admin_user_delete(uid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    p = db.get(models.User, uid)
    if p and p.id != user.id:
        # bu odam ijrochi bo'lgan заявкаларни bo'shatamiz
        db.query(models.Request).filter(models.Request.assigned_to == uid)\
            .update({models.Request.assigned_to: None}, synchronize_session=False)
        # bu odam yaratgan заявкаларni birma-bir o'chiramiz (cascade: izoh/tarix/fayl)
        reqs = db.query(models.Request).filter(models.Request.created_by == uid).all()
        for r in reqs:
            for att in r.attachments:
                try:
                    fp = att.file_path.lstrip("/")
                    if os.path.exists(fp):
                        os.remove(fp)
                except Exception:
                    pass
            db.query(models.Notification).filter(
                models.Notification.link == f"/requests/{r.id}").delete(synchronize_session=False)
            db.delete(r)
        # bu odamning izohlari va bildirishnomalarini o'chiramiz
        db.query(models.Comment).filter(models.Comment.user_id == uid)\
            .delete(synchronize_session=False)
        db.query(models.Notification).filter(models.Notification.user_id == uid)\
            .delete(synchronize_session=False)
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/users/{uid}/edit")
def admin_user_edit(uid: int, request: Request, full_name: str = Form(...),
                    email: str = Form(""), role: str = Form("executor"),
                    department_id: Optional[int] = Form(None),
                    phone: str = Form(""), telegram_chat_id: str = Form(""),
                    password: str = Form(""), kpp_branch_ids: List[int] = Form([]),
                    db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    p = db.get(models.User, uid)
    if p:
        p.full_name = full_name.strip()
        # email — boshqa odamda band bo'lmasa o'zgartiramiz
        new_email = email.lower().strip()
        if new_email and new_email != p.email:
            taken = db.query(models.User).filter(
                models.User.email == new_email, models.User.id != uid).first()
            if not taken:
                p.email = new_email
        p.role = Role(role)
        p.department_id = department_id
        p.phone = phone.strip()
        p.telegram_chat_id = telegram_chat_id.strip()
        # КПП filiallari
        if role == "kpp":
            p.visible_branches = db.query(models.Branch).filter(
                models.Branch.id.in_(kpp_branch_ids)).all() if kpp_branch_ids else []
        else:
            p.visible_branches = []
        # parol — faqat kiritilgan bo'lsa o'zgartiramiz
        if password.strip():
            p.hashed_password = auth.hash_password(password.strip())
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/categories/create")
def admin_cat_create(request: Request, name: str = Form(...), icon: str = Form("🗂️"),
                     color: str = Form("#2563eb"), subcategories: str = Form(""),
                     db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    if db.query(models.Department).count() < 10:
        d = models.Department(name=name.strip(), icon=(icon.strip() or "🗂️"), color=color)
        db.add(d); db.flush()
        for line in subcategories.splitlines():
            nm = line.strip()
            if nm:
                db.add(models.Subcategory(name=nm, department_id=d.id))
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/categories/{dep_id}/delete")
def admin_cat_delete(dep_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    d = db.get(models.Department, dep_id)
    if d:
        db.query(models.User).filter(models.User.department_id == dep_id)\
            .update({models.User.department_id: None}, synchronize_session=False)
        for r in db.query(models.Request).filter(models.Request.department_id == dep_id).all():
            for att in r.attachments:
                try:
                    fp = att.file_path.lstrip("/")
                    if os.path.exists(fp):
                        os.remove(fp)
                except Exception:
                    pass
            db.query(models.Notification).filter(
                models.Notification.link == f"/requests/{r.id}").delete(synchronize_session=False)
            db.delete(r)
        db.delete(d); db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/categories/{dep_id}/edit")
def admin_cat_edit(dep_id: int, request: Request, name: str = Form(...),
                   icon: str = Form("🗂️"), color: str = Form("#2563eb"),
                   subcategories: str = Form(""), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    d = db.get(models.Department, dep_id)
    if d:
        d.name = name.strip()
        d.icon = icon.strip() or "🗂️"
        d.color = color
        # podkategoriyalarni qayta yozamiz (avval заявкалардаги ishorani bo'shatamiz)
        old_ids = [s.id for s in db.query(models.Subcategory).filter(
            models.Subcategory.department_id == dep_id).all()]
        if old_ids:
            db.query(models.Request).filter(
                models.Request.subcategory_id.in_(old_ids)).update(
                {models.Request.subcategory_id: None}, synchronize_session=False)
        db.query(models.Subcategory).filter(
            models.Subcategory.department_id == dep_id).delete()
        for line in subcategories.splitlines():
            nm = line.strip()
            if nm:
                db.add(models.Subcategory(name=nm, department_id=dep_id))
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/branches/create")
def admin_branch_create(request: Request, name: str = Form(...), location: str = Form(""),
                        phone: str = Form(""), director_name: str = Form(""),
                        login_email: str = Form(""), password: str = Form(""),
                        db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    b = models.Branch(name=name.strip(), location=location.strip(),
                      phone=phone.strip(), director_name=director_name.strip())
    db.add(b); db.flush()
    # filial uchun login (klient) yaratish
    login_email = login_email.lower().strip()
    if login_email and not db.query(models.User).filter(models.User.email == login_email).first():
        db.add(models.User(full_name=name.strip(), email=login_email,
                           hashed_password=auth.hash_password(password or "12345678"),
                           role=Role.client, user_branch_id=b.id, is_active=True))
    db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/branches/{bid}/delete")
def admin_branch_delete(bid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    b = db.get(models.Branch, bid)
    if b:
        db.query(models.Request).filter(models.Request.branch_id == bid)\
            .update({models.Request.branch_id: None})
        db.delete(b); db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/branches/{bid}/edit")
def admin_branch_edit(bid: int, request: Request, name: str = Form(...),
                      location: str = Form(""), phone: str = Form(""),
                      director_name: str = Form(""), login_email: str = Form(""),
                      password: str = Form(""), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    b = db.get(models.Branch, bid)
    if b:
        b.name = name.strip()
        b.location = location.strip()
        b.phone = phone.strip()
        b.director_name = director_name.strip()
        # filial logini (client akkaunt)
        login_email = login_email.lower().strip()
        client = db.query(models.User).filter(
            models.User.user_branch_id == bid, models.User.role == Role.client).first()
        if login_email:
            taken = db.query(models.User).filter(
                models.User.email == login_email,
                models.User.user_branch_id != bid).first()
            if client:
                # mavjud login: email (band bo'lmasa) va parol (kiritilgan bo'lsa) yangilanadi
                if not taken and login_email != client.email:
                    client.email = login_email
                if password.strip():
                    client.hashed_password = auth.hash_password(password.strip())
            elif not taken:
                # login yo'q edi — yangi client akkaunt yaratamiz
                db.add(models.User(full_name=b.name, email=login_email,
                                   hashed_password=auth.hash_password(password.strip() or "12345678"),
                                   role=Role.client, user_branch_id=bid, is_active=True))
        elif client and password.strip():
            # email o'zgarmasa ham — faqat parol yangilash
            client.hashed_password = auth.hash_password(password.strip())
        db.commit()
    return RedirectResponse("/admin", 302)


# ===================== JSON API =====================
@app.get("/api/departments")
def api_departments(db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name, "icon": d.icon, "color": d.color,
             "count": len(d.requests)} for d in db.query(models.Department).all()]


@app.get("/api/requests")
def api_requests(department_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Request)
    if department_id:
        q = q.filter(models.Request.department_id == department_id)
    return [{"id": r.id, "title": r.title, "status": r.status.value,
             "priority": r.priority.value,
             "department": r.department.name if r.department else None,
             "assignee": ", ".join(a.full_name for a in r.assignees) if r.assignees else None}
            for r in q.order_by(models.Request.created_at.desc()).all()]


# ===================== STOP-LIST =====================
def is_supply(user):
    """Foydalanuvchi Снабжение bo'limidami?"""
    return user.department is not None and "набжен" in (user.department.name or "").lower()


def can_see_stoplist(user):
    # Снабжение bo'limi, filial direktorlari, viewer (ADMIN EMAS)
    return user.role in (Role.client, Role.viewer) or is_supply(user)


def can_manage_menu(user):
    """Menyu boshqaruvi — faqat Снабжение bo'limidagi menejer."""
    return user.role == Role.manager and is_supply(user)


@app.get("/stoplist", response_class=HTMLResponse)
def stoplist_page(request: Request, sync: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if not can_see_stoplist(user):
        return RedirectResponse("/dashboard", 302)
    is_client = user.role == Role.client
    menu_items = db.query(models.MenuItem).filter(models.MenuItem.is_active == True)\
        .order_by(models.MenuItem.name).all() if is_client else []
    q = db.query(models.StopEntry).filter(models.StopEntry.resolved == False)
    if is_client:
        q = q.filter(models.StopEntry.branch_id == user.user_branch_id)
    entries = q.order_by(models.StopEntry.created_at.desc()).all()
    return templates.TemplateResponse(request, "stoplist.html", {
        "request": request, "user": user, "active": "stoplist",
        "menu_items": menu_items, "entries": entries, "is_client": is_client,
        "can_resolve": is_supply(user) or is_client,
        "can_comment": is_supply(user), "sync_msg": sync,
    })


@app.get("/stoplist/history", response_class=HTMLResponse)
def stoplist_history_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if not can_see_stoplist(user):
        return RedirectResponse("/dashboard", 302)
    is_client = user.role == Role.client
    hq = db.query(models.StopEntry).filter(models.StopEntry.resolved == True)
    if is_client:
        hq = hq.filter(models.StopEntry.branch_id == user.user_branch_id)
    history = hq.order_by(models.StopEntry.resolved_at.desc().nullslast()).limit(500).all()
    return templates.TemplateResponse(request, "stoplist_history.html", {
        "request": request, "user": user, "active": "stophistory",
        "history": history, "is_client": is_client,
    })


@app.get("/stoplist/menu", response_class=HTMLResponse)
def stoplist_menu_page(request: Request, sync: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if not can_manage_menu(user):
        return RedirectResponse("/dashboard", 302)
    menu_items = db.query(models.MenuItem).order_by(models.MenuItem.name).all()
    return templates.TemplateResponse(request, "stoplist_menu.html", {
        "request": request, "user": user, "active": "stopmenu",
        "menu_items": menu_items, "sync_msg": sync,
    })


@app.post("/stoplist/add")
def stoplist_add(request: Request, menu_name: List[str] = Form([]),
                 reason: str = Form(...), comment: str = Form(""),
                 db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.client or not user.user_branch_id:
        return RedirectResponse("/login", 302)
    if reason not in REASON_LABELS:
        return RedirectResponse("/stoplist", 302)
    added = 0
    for nm in menu_name:
        mi = db.query(models.MenuItem).filter(
            models.MenuItem.name == nm.strip(),
            models.MenuItem.is_active == True).first()
        if not mi:
            continue
        exists = db.query(models.StopEntry).filter(
            models.StopEntry.branch_id == user.user_branch_id,
            models.StopEntry.menu_item_id == mi.id,
            models.StopEntry.resolved == False).first()
        if not exists:
            db.add(models.StopEntry(branch_id=user.user_branch_id, menu_item_id=mi.id,
                   reason=reason, comment=comment.strip(), created_by=user.id))
            added += 1
    if added:
        db.commit()
    return RedirectResponse("/stoplist", 302)


@app.post("/stoplist/{sid}/comment")
def stoplist_comment(sid: int, request: Request, comment: str = Form(""),
                     db: Session = Depends(get_db)):
    """Снабжение xodimi o'z izohini (supply_comment) qo'shadi/tahrirlaydi."""
    user = current_user(request, db)
    if not user or not is_supply(user):
        return RedirectResponse("/login", 302)
    e = db.get(models.StopEntry, sid)
    if e:
        e.supply_comment = comment.strip()
        db.commit()
    return RedirectResponse("/stoplist", 302)


@app.post("/stoplist/{sid}/resolve")
def stoplist_resolve(sid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    e = db.get(models.StopEntry, sid)
    if e:
        # klient faqat o'z filialini, aks holda snabjenie xodimi
        ok = (user.role == Role.client and e.branch_id == user.user_branch_id) \
            or is_supply(user)
        if ok:
            e.resolved = True
            e.resolved_at = datetime.utcnow() + timedelta(hours=5)
            db.commit()
    return RedirectResponse("/stoplist", 302)


@app.post("/stoplist/menu/add")
def stoplist_menu_add(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not can_manage_menu(user):
        return RedirectResponse("/login", 302)
    for line in name.splitlines():
        nm = line.strip()
        if nm and not db.query(models.MenuItem).filter(models.MenuItem.name == nm).first():
            db.add(models.MenuItem(name=nm))
    db.commit()
    return RedirectResponse("/stoplist/menu", 302)


@app.post("/stoplist/menu/{mid}/delete")
def stoplist_menu_delete(mid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not can_manage_menu(user):
        return RedirectResponse("/login", 302)
    m = db.get(models.MenuItem, mid)
    if m:
        db.query(models.StopEntry).filter(models.StopEntry.menu_item_id == mid).delete()
        db.delete(m); db.commit()
    return RedirectResponse("/stoplist/menu", 302)


# ===================== MENYU YUKLASH (Excel/PDF) + STOP-LIST EXPORT =====================
def _parse_menu_file(filename, data):
    """Excel (.xlsx) yoki PDF fayldan taom nomlarini ajratib oladi. Nomlar ro'yxatini qaytaradi."""
    names = []
    fn = (filename or "").lower()
    if fn.endswith((".xlsx", ".xlsm")):
        import openpyxl, io
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if isinstance(cell, str) and cell.strip() and len(cell.strip()) >= 2:
                        names.append(cell.strip())
        wb.close()
    elif fn.endswith(".pdf"):
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        for page in reader.pages:
            for line in (page.extract_text() or "").splitlines():
                s = line.strip()
                if len(s) >= 2:
                    names.append(s)
    else:
        raise ValueError("Faqat .xlsx yoki .pdf")
    # takrorlarni olib tashlaymiz (tartibni saqlab)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out


@app.post("/stoplist/menu/upload")
def stoplist_menu_upload(request: Request, replace: str = Form(""),
                         file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not can_manage_menu(user):
        return RedirectResponse("/login", 302)
    try:
        data = file.file.read()
        names = _parse_menu_file(file.filename, data)
    except Exception as e:
        return RedirectResponse(f"/stoplist/menu?sync={urllib.parse.quote('Ошибка файла: ' + str(e)[:120])}", 302)
    if replace == "1":
        # eski menyuni o'chiramiz (stop-listlar bilan)
        db.query(models.StopEntry).delete(synchronize_session=False)
        db.query(models.MenuItem).delete(synchronize_session=False)
    added = 0
    for nm in names:
        if not db.query(models.MenuItem).filter(models.MenuItem.name == nm).first():
            db.add(models.MenuItem(name=nm, is_active=True)); added += 1
    db.commit()
    msg = f"Меню загружено: {added} новых из {len(names)} (файл: {file.filename})"
    return RedirectResponse(f"/stoplist/menu?sync={urllib.parse.quote(msg)}", 302)


@app.post("/stoplist/menu/clear")
def stoplist_menu_clear(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not can_manage_menu(user):
        return RedirectResponse("/login", 302)
    db.query(models.StopEntry).delete(synchronize_session=False)
    db.query(models.MenuItem).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/stoplist/menu?sync=" + urllib.parse.quote("Меню очищено"), 302)


def _xlsx_title(name, used):
    bad = '[]:*?/\\'
    t = "".join(c for c in (name or "—") if c not in bad)[:28] or "Лист"
    base = t; i = 2
    while t in used:
        t = f"{base[:25]} {i}"; i += 1
    used.add(t); return t


@app.get("/stoplist/export")
def stoplist_export(request: Request, mode: str = "active", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not can_see_stoplist(user):
        return RedirectResponse("/login", 302)
    import openpyxl, io
    from fastapi.responses import StreamingResponse
    resolved = (mode == "history")
    q = db.query(models.StopEntry).filter(models.StopEntry.resolved == resolved)
    if user.role == Role.client:
        q = q.filter(models.StopEntry.branch_id == user.user_branch_id)
    order = models.StopEntry.resolved_at.desc().nullslast() if resolved else models.StopEntry.created_at.desc()
    entries = q.order_by(order).all()

    headers = ["Филиал", "Блюдо", "Причина", "Комм. филиала", "Комм. снабжения", "Добавлено"] + (["Убрано"] if resolved else [])
    widths = (24, 34, 26, 30, 30, 18) + ((18,) if resolved else ())

    def row(e):
        r = [e.branch.name if e.branch else "", e.menu_item.name if e.menu_item else "",
             REASON_LABELS.get(e.reason, e.reason), e.comment or "", e.supply_comment or "",
             e.created_at.strftime("%d.%m.%Y %H:%M")]
        if resolved:
            r.append(e.resolved_at.strftime("%d.%m.%Y %H:%M") if e.resolved_at else "")
        return r

    def fill(ws, items):
        ws.append(headers)
        for e in items:
            ws.append(row(e))
        for col, w in zip("ABCDEFG", widths):
            ws.column_dimensions[col].width = w

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Все филиалы"
    fill(ws, entries)
    # har bir filial uchun alohida varaq (klient bo'lmasa)
    if user.role != Role.client:
        by_branch = {}
        for e in entries:
            bn = e.branch.name if e.branch else "—"
            by_branch.setdefault(bn, []).append(e)
        used = {"Все филиалы"}
        for bn in sorted(by_branch):
            fill(wb.create_sheet(_xlsx_title(bn, used)), by_branch[bn])

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    tag = "istoriya" if resolved else "stop-list"
    fname = f"{tag}-{(datetime.utcnow() + timedelta(hours=5)).strftime('%Y%m%d-%H%M')}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
