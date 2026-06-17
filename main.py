"""MAXWAY — ishlarni saqlash va ijrochilarga yo'naltirish tizimi (FastAPI)."""
import os
import json
import urllib.request
import urllib.parse
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
    checks = [("attachments", "stage", "VARCHAR(10) DEFAULT 'request'")]
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

app = FastAPI(title="MAXWAY")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
print(">>> [MAXWAY] ilova tayyor ✅", flush=True)

STATUS_LABELS = {
    "new": "Новая", "approved": "Одобрена", "in_progress": "В работе",
    "on_check": "На проверке", "done": "Выполнена", "rejected": "Отклонена",
}
PRIORITY_LABELS = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
ROLE_LABELS = {"admin": "АДМИН", "manager": "МЕНЕДЖЕР", "executor": "ИСПОЛНИТЕЛЬ", "client": "КЛИЕНТ"}

templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS, PRIORITY_LABELS=PRIORITY_LABELS,
    ROLE_LABELS=ROLE_LABELS, APP_NAME="MAXWAY", now=datetime.utcnow,
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
    """Klient bo'lsa faqat o'z filiali zayavkalari, aks holда hammasi."""
    q = db.query(models.Request)
    if user.role == Role.client:
        q = q.filter(models.Request.branch_id == user.user_branch_id)
    return q


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
            {"request": request, "error": "Email yoki parol noto'g'ri"}, status_code=401)
    token = auth.create_access_token(user.id)
    resp = RedirectResponse("/dashboard", 302)
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, max_age=604800)
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
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, max_age=604800)
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
    ctx = {
        "request": request, "user": user, "active": "dashboard",
        "total": q.count(),
        "new": q.filter(models.Request.status == Status.new).count(),
        "in_progress": q.filter(models.Request.status == Status.in_progress).count(),
        "done": q.filter(models.Request.status == Status.done).count(),
        "unassigned": q.filter(models.Request.assigned_to.is_(None)).count(),
        "departments": db.query(models.Department).all(),
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
    return templates.TemplateResponse(request, "requests.html", {
        "request": request, "user": user, "active": "requests",
        "items": items, "departments": db.query(models.Department).all(),
        "executors": db.query(models.User).all(), "selected_dep": selected_dep,
        "selected_status": status, "counts": counts, "search": q or "",
        "branches": db.query(models.Branch).order_by(models.Branch.name).all(),
    })


@app.get("/requests/{req_id}", response_class=HTMLResponse)
def request_detail(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if not r:
        raise HTTPException(404, "Заявка топилмади")
    if user.role == Role.client and r.branch_id != user.user_branch_id:
        return RedirectResponse("/requests", 302)
    return templates.TemplateResponse(request, "request_detail.html", {
        "request": request, "user": user, "active": "requests", "r": r,
        "executors": db.query(models.User).filter(models.User.is_active == True).all(),
    })


@app.post("/requests/create")
def create_request(request: Request, title: str = Form(...), description: str = Form(""),
                   department_id: int = Form(...), priority: str = Form("medium"),
                   customer_name: str = Form(""), customer_email: str = Form(""),
                   customer_phone: str = Form(""), branch_id: Optional[int] = Form(None),
                   deadline: str = Form(""), photos: List[UploadFile] = File([]),
                   videos: List[UploadFile] = File([]), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    dl = None
    if deadline:
        try:
            dl = datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            dl = None
    branch_name = ""
    if user.role == Role.client and user.user_branch_id:
        branch_id = user.user_branch_id
    if branch_id:
        b = db.get(models.Branch, branch_id)
        branch_name = b.name if b else ""
    cust_email = customer_email.strip() or user.email   # bo'sh bo'lsa login email
    r = models.Request(title=title.strip(), description=description.strip(),
                       department_id=department_id, priority=Priority(priority),
                       status=Status.new, created_by=user.id,
                       customer_name=customer_name.strip(), customer_email=cust_email,
                       customer_phone=customer_phone.strip(), branch=branch_name,
                       branch_id=branch_id, deadline=dl)
    db.add(r); db.flush()
    add_history(db, r, Status.new, "Заявка яратилди")

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
        models.User.role.in_([Role.executor, Role.manager, Role.admin]),
        ((models.User.department_id == r.department_id) | (models.User.role == Role.admin))
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
        db.add(models.Notification(user_id=u.id, text=site_text, link=link))
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
        .order_by(models.Notification.created_at.desc()).limit(20).all()
    unread = db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.is_read == False).count()
    return JSONResponse({
        "unread": unread,
        "items": [{"text": n.text, "link": n.link, "is_read": n.is_read,
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
        r.assigned_to = assigned_to
        if r.status in (Status.new, Status.rejected):
            r.status = Status.in_progress
            add_history(db, r, Status.in_progress, "Ижрочи бириктирилди")
        db.commit()
        # Telegram xabari (ijrochining chat_id si bo'lsa)
        assignee = db.get(models.User, assigned_to)
        if assignee and assignee.telegram_chat_id:
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
    """Заявкани butunlay o'chiradi — faqat admin."""
    user = current_user(request, db)
    if not user or user.role != Role.admin:
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
        r.status = Status(status)
        add_history(db, r, Status(status), "Статус ўзгартирилди")
        db.commit()
    ref = request.headers.get("referer", f"/requests/{req_id}")
    return RedirectResponse(ref, 302)


@app.post("/requests/{req_id}/comment")
def add_comment(req_id: int, request: Request, text: str = Form(...),
                db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    r = db.get(models.Request, req_id)
    if r and text.strip():
        db.add(models.Comment(request_id=req_id, user_id=user.id, text=text.strip()))
        db.commit()
        # zayavка egasiga bildirishnoma (boshqa odam izoh yozsa)
        if r.created_by and r.created_by != user.id:
            link = f"/requests/{r.id}"
            db.add(models.Notification(user_id=r.created_by,
                   text=f"Новый комментарий к «{r.title}»: {text.strip()[:60]}", link=link))
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
    db.commit()
    # zayavка egasiga (klиентга) bildirishnoma
    if r.created_by and r.created_by != user.id:
        link = f"/requests/{r.id}"
        db.add(models.Notification(user_id=r.created_by,
               text=f"Добавлено решение по заявке «{r.title}»", link=link))
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
                   bio: str = Form(""), current_password: str = Form(""),
                   new_password: str = Form(""), confirm_password: str = Form(""),
                   photo: UploadFile = File(None), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    user.full_name = full_name.strip()
    user.phone = phone.strip()
    user.bio = bio.strip()
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
    people = db.query(models.User).order_by(models.User.full_name).all()
    stats = {}
    for p in people:
        rq = db.query(models.Request).filter(models.Request.assigned_to == p.id)
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
        rq = db.query(models.Request).filter(models.Request.assigned_to == e.id)
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
            .update({models.User.department_id: None})
        db.query(models.Request).filter(models.Request.department_id == dep_id).delete()
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
    return templates.TemplateResponse(request, "admin.html", {
        "request": request, "user": user, "active": "admin",
        "users": db.query(models.User).order_by(models.User.full_name).all(),
        "departments": db.query(models.Department).all(),
        "branches": db.query(models.Branch).order_by(models.Branch.name).all(),
    })


@app.post("/admin/users/create")
def admin_user_create(request: Request, full_name: str = Form(...), email: str = Form(...),
                      password: str = Form("12345678"), role: str = Form("executor"),
                      department_id: Optional[int] = Form(None), phone: str = Form(""),
                      db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    email = email.lower().strip()
    if not db.query(models.User).filter(models.User.email == email).first():
        db.add(models.User(full_name=full_name.strip(), email=email,
                           hashed_password=auth.hash_password(password or "12345678"),
                           role=Role(role), department_id=department_id,
                           phone=phone.strip(), is_active=True))
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/users/{uid}/delete")
def admin_user_delete(uid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    p = db.get(models.User, uid)
    if p and p.id != user.id:
        db.query(models.Request).filter(models.Request.assigned_to == uid)\
            .update({models.Request.assigned_to: None})
        db.query(models.Request).filter(models.Request.created_by == uid).delete()
        db.delete(p); db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/users/{uid}/edit")
def admin_user_edit(uid: int, request: Request, full_name: str = Form(...),
                    email: str = Form(""), role: str = Form("executor"),
                    department_id: Optional[int] = Form(None),
                    phone: str = Form(""), telegram_chat_id: str = Form(""),
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
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/categories/create")
def admin_cat_create(request: Request, name: str = Form(...), icon: str = Form("🗂️"),
                     color: str = Form("#2563eb"), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    if db.query(models.Department).count() < 10:
        db.add(models.Department(name=name.strip(), icon=(icon.strip() or "🗂️"), color=color))
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
            .update({models.User.department_id: None})
        db.query(models.Request).filter(models.Request.department_id == dep_id).delete()
        db.delete(d); db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/categories/{dep_id}/edit")
def admin_cat_edit(dep_id: int, request: Request, name: str = Form(...),
                   icon: str = Form("🗂️"), color: str = Form("#2563eb"),
                   db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    d = db.get(models.Department, dep_id)
    if d:
        d.name = name.strip()
        d.icon = icon.strip() or "🗂️"
        d.color = color
        db.commit()
    return RedirectResponse("/admin", 302)


@app.post("/admin/branches/create")
def admin_branch_create(request: Request, name: str = Form(...), location: str = Form(""),
                        login_email: str = Form(""), password: str = Form(""),
                        db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    b = models.Branch(name=name.strip(), location=location.strip())
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
                      location: str = Form(""), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role != Role.admin:
        return RedirectResponse("/login", 302)
    b = db.get(models.Branch, bid)
    if b:
        b.name = name.strip()
        b.location = location.strip()
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
             "assignee": r.assignee.full_name if r.assignee else None}
            for r in q.order_by(models.Request.created_at.desc()).all()]
