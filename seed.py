"""Demo ma'lumot:  python seed.py  (yoki birinchi deploy'da avtomatik)"""
from datetime import datetime, timedelta
from app.database import Base, engine, SessionLocal
from app import models, auth
from app.models import Role, Status, Priority


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    DEPARTMENTS = [
        ("ИТ", "💻", "#6366f1", "Axborot texnologiyalari"),
        ("HR", "👥", "#ec4899", "Kadrlar"),
        ("Бухгалтерия", "📊", "#16a34a", "Buxgalteriya"),
        ("Маркетинг", "📣", "#f59e0b", "Marketing"),
        ("Логистика", "🚚", "#0891b2", "Logistika"),
        ("Производство", "🏭", "#dc2626", "Ishlab chiqarish"),
        ("Снабжение", "📦", "#7c3aed", "Ta'minot"),
        ("Юридический", "⚖️", "#0f766e", "Yuridik"),
        ("Охрана", "🛡️", "#475569", "Xavfsizlik"),
        ("Клиенты", "🤝", "#2563eb", "Mijozlar"),
    ]

    if db.query(models.Department).count() == 0:
        for name, icon, color, desc in DEPARTMENTS:
            db.add(models.Department(name=name, icon=icon, color=color, description=desc))
        db.commit()
        print(f"✅ {len(DEPARTMENTS)} ta bo'lim")

    it = db.query(models.Department).filter(models.Department.name == "ИТ").first()

    if not db.query(models.User).filter(models.User.email == "a.ruzikulov@gmail.com").first():
        db.add(models.User(
            full_name="Aslidin Ruzikulov", email="a.ruzikulov@gmail.com",
            hashed_password=auth.hash_password("12345678"), role=Role.admin,
            department_id=it.id, phone="+998913216163", position="Начальник отдела ИТ",
            specialization="ИТ и сети", schedule="5/2 09:00–18:00", experience="10 лет",
            telegram="@asliddin", is_active=True))
        for nm, em, pos in [
            ("Sardor Aliyev", "sardor@maxway.uz", "Системный администратор"),
            ("Dilnoza Yusupova", "dilnoza@maxway.uz", "Специалист поддержки"),
            ("Bek Toshev", "marsel@gmail.com", "Инженер")]:
            db.add(models.User(full_name=nm, email=em,
                hashed_password=auth.hash_password("12345678"), role=Role.executor,
                department_id=it.id, position=pos, specialization="ИТ",
                schedule="5/2 09:00–18:00", experience="3 года", is_active=True))
        db.commit()
        print("✅ Admin: a.ruzikulov@gmail.com / 12345678")

    if db.query(models.Branch).count() == 0:
        BRANCHES = [
            ("MW06-NEXT", "Iqos, Бабура улица, Ракатбаши махалля, Яккасарайский район, Ташкент, 100000, Узбекистан"),
            ("MW01-GRANDMIR", "Чиланзарский район, Ташкент, Узбекистан"),
            ("MW03-FONTAN", "Юнусабадский район, Ташкент, Узбекистан"),
            ("MW12-ELDOR", "Мирзо-Улугбекский район, Ташкент, Узбекистан"),
        ]
        for nm, loc in BRANCHES:
            db.add(models.Branch(name=nm, location=loc))
        db.commit()
        print(f"✅ {len(BRANCHES)} ta filial")
        # MW12-ELDOR filiali uchun klient login
        eldor = db.query(models.Branch).filter(models.Branch.name == "MW12-ELDOR").first()
        if eldor and not db.query(models.User).filter(models.User.email == "eldor@maxway.uz").first():
            db.add(models.User(full_name="MW12-ELDOR", email="eldor@maxway.uz",
                               hashed_password=auth.hash_password("12345678"),
                               role=Role.client, user_branch_id=eldor.id, is_active=True))
            db.commit()
            print("✅ Filial klient login: eldor@maxway.uz / 12345678")

    if db.query(models.Request).count() == 0:
        admin = db.query(models.User).filter(models.User.email == "a.ruzikulov@gmail.com").first()
        branches = db.query(models.Branch).all()
        now = datetime.utcnow()
        data = [
            ("Ekran ishlamayapti", Status.approved, Priority.medium, "Паркент", -16, "Monoblok kassa ekrani o'chgan"),
            ("Ashipka Epos", Status.approved, Priority.high, "Некст", -22, "kartadan pul yechilgan chek chiqmadi"),
            ("Dostavka cheki yopilmayapti", Status.done, Priority.medium, "ГрандМир", 0, "chek qizarib qolgan"),
            ("Televizor ekraniga palasa tushib qolgan", Status.approved, Priority.medium, "ГрандМир", 0, "reklama televizori"),
            ("Internet sekin", Status.new, Priority.low, "Фонтан", 5, "Wi-Fi past tezlik"),
            ("Email parolni tiklash", Status.new, Priority.medium, "Eldor", 3, "xodim parolни unutgan"),
            ("1C yangilash", Status.done, Priority.high, "Eldor", -2, "1C versiya yangilandi"),
            ("Router almashtirish", Status.in_progress, Priority.medium, "Мукумий", 4, "eski router buzilgan"),
        ]
        execs = db.query(models.User).filter(models.User.role == Role.executor).all()
        for i, (title, st, pr, cust, dl_days, desc) in enumerate(data):
            br = branches[i % len(branches)] if branches else None
            r = models.Request(
                title=title, description=desc, department_id=it.id, created_by=admin.id,
                status=st, priority=pr, customer_name=cust,
                customer_email=cust.lower() + "@gmail.com", customer_phone="+998944081196",
                branch=(br.name if br else ""), branch_id=(br.id if br else None),
                deadline=now + timedelta(days=dl_days),
                assigned_to=admin.id if st in (Status.in_progress, Status.done, Status.approved) else None)
            db.add(r); db.flush()
            db.add(models.StatusHistory(request_id=r.id, status=Status.new,
                note="Заявка яратилди", created_at=now - timedelta(days=2)))
            if st != Status.new:
                db.add(models.StatusHistory(request_id=r.id, status=st,
                    note="Статус ўзгарди", created_at=now - timedelta(days=1)))
            if i < 2:
                db.add(models.Comment(request_id=r.id, user_id=admin.id,
                    text="nima oshibka ko'rsatgan rasmi bilan tashang, yoki masala hal bo'ldimi"))
        db.commit()
        print("✅ Namuna zayavkalar + izoh + tarix")

    db.close()
    print("\n🎉 Tayyor!  uvicorn main:app --reload")


if __name__ == "__main__":
    seed()