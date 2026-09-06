"""Ma'lumotlar bazasi modellari (boyitilgan)."""
import enum
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Boolean,
    Table, Enum as SAEnum
)
from sqlalchemy.orm import relationship

from .database import Base


def tashkent_now():
    """Toshkent vaqti (UTC+5)."""
    return datetime.utcnow() + timedelta(hours=5)


class Role(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    executor = "executor"
    client = "client"          # filial foydalanuvchisi
    viewer = "viewer"          # kuzatuvchi — hamma bo'limni ko'radi (faqat o'qish)
    kpp = "kpp"                # КПП — admin belgilagan filiallarni ko'radi (faqat o'qish)


class Status(str, enum.Enum):
    new = "new"                # Новая
    approved = "approved"      # Одобрена
    in_progress = "in_progress"  # В работе
    on_check = "on_check"      # На проверке
    done = "done"              # Выполнена
    rejected = "rejected"      # Отклонена


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    icon = Column(String(20), default="🗂️")
    color = Column(String(20), default="#2563eb")
    description = Column(String(255), default="")
    created_at = Column(DateTime, default=tashkent_now)

    users = relationship("User", back_populates="department")
    requests = relationship("Request", back_populates="department")
    subcategories = relationship("Subcategory", back_populates="department",
                                 cascade="all, delete-orphan",
                                 order_by="Subcategory.name")


class Subcategory(Base):
    """Podkategoriya — biror kategoriyaga tegishli bo'lim."""
    __tablename__ = "subcategories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    created_at = Column(DateTime, default=tashkent_now)

    department = relationship("Department", back_populates="subcategories")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SAEnum(Role), default=Role.executor)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    # boy profil maydonlari
    phone = Column(String(40), default="")
    position = Column(String(120), default="")      # lavozim
    specialization = Column(String(120), default="")  # mutaxassislik
    schedule = Column(String(80), default="")        # ish jadvali
    experience = Column(String(40), default="")      # staj
    telegram = Column(String(80), default="")        # telegram username
    telegram_chat_id = Column(String(40), default="")  # bot xabar yuborish uchun
    bio = Column(Text, default="")
    avatar = Column(String(255), default="")         # profil rasmi yo'li
    is_active = Column(Boolean, default=True)
    user_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)  # klient filiali
    created_at = Column(DateTime, default=tashkent_now)

    department = relationship("Department", back_populates="users")
    branch = relationship("Branch")
    visible_branches = relationship("Branch", secondary="kpp_branches")
    perms = Column(Text, nullable=True)   # admin belgilagan ruxsatlar (JSON), null = rol bo'yicha
    created_requests = relationship(
        "Request", back_populates="creator", foreign_keys="Request.created_by")
    assigned_requests = relationship(
        "Request", back_populates="assignee", foreign_keys="Request.assigned_to")


# КПП foydalanuvchisi ko'ra oladigan filiallar (many-to-many)
kpp_branches = Table(
    "kpp_branches", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", Integer, ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)


# bir zayavkaga bir nechta ijrochi (many-to-many)
request_assignees = Table(
    "request_assignees", Base.metadata,
    Column("request_id", Integer, ForeignKey("requests.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Request(Base):
    __tablename__ = "requests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(SAEnum(Status), default=Status.new)
    priority = Column(SAEnum(Priority), default=Priority.medium)

    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    # buyurtmachi (заказчик)
    customer_name = Column(String(120), default="")
    customer_email = Column(String(120), default="")
    customer_phone = Column(String(40), default="")
    branch = Column(String(160), default="")        # filial nomi (matn, zaxira)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)

    deadline = Column(DateTime, nullable=True)       # дедлайн
    dep_number = Column(Integer, nullable=True)      # bo'lim ichidagi tartib raqami (1 dan)
    reject_reason = Column(Text, default="")         # rad etish sababi

    created_at = Column(DateTime, default=tashkent_now)
    updated_at = Column(DateTime, default=tashkent_now, onupdate=tashkent_now)

    department = relationship("Department", back_populates="requests")
    subcategory = relationship("Subcategory")
    creator = relationship("User", back_populates="created_requests",
                           foreign_keys=[created_by])
    assignee = relationship("User", back_populates="assigned_requests",
                            foreign_keys=[assigned_to])
    assignees = relationship("User", secondary="request_assignees")
    branch_obj = relationship("Branch")
    comments = relationship("Comment", back_populates="request",
                            cascade="all, delete-orphan",
                            order_by="Comment.created_at")
    history = relationship("StatusHistory", back_populates="request",
                           cascade="all, delete-orphan",
                           order_by="StatusHistory.created_at")
    attachments = relationship("Attachment", back_populates="request",
                               cascade="all, delete-orphan")

    @property
    def is_overdue(self) -> bool:
        if self.deadline and self.status != Status.done and self.status != Status.rejected:
            return tashkent_now() > self.deadline
        return False


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=tashkent_now)

    request = relationship("Request", back_populates="comments")
    user = relationship("User")


class StatusHistory(Base):
    __tablename__ = "status_history"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    status = Column(SAEnum(Status), nullable=False)
    note = Column(String(255), default="")
    created_at = Column(DateTime, default=tashkent_now)

    request = relationship("Request", back_populates="history")


class Branch(Base):
    """Filial — nom/kod va lokatsiya (manzil)."""
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)       # masalan: MW06-NEXT
    location = Column(Text, default="")              # to'liq manzil / lokatsiya
    phone = Column(String(40), default="")           # filial telefon raqami
    director_name = Column(String(120), default="")  # filial direktori (buyurtmachi)
    # filial xodimlarining telegram chat_id lari (vergul bilan) — izoh/yechim xabari uchun
    tg_chat_ids = Column(Text, default="")
    # iikoCloud bog'lanishi: filial = bitta terminal guruh
    iiko_terminal_id = Column(String(64), default="", index=True)
    iiko_org_id = Column(String(64), default="")
    iiko_terminal_name = Column(String(160), default="")   # admin panelida ko'rsatish uchun
    # birinchi sinxronizatsiya vaqti — o'sha safar telegram jim turadi
    iiko_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=tashkent_now)


class Attachment(Base):
    """Zayavkaga biriktirilgan rasm/video."""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    file_path = Column(String(255), nullable=False)
    kind = Column(String(10), default="image")   # image | video
    stage = Column(String(10), default="request")  # request (muammo) | solution (yechim)
    created_at = Column(DateTime, default=tashkent_now)

    request = relationship("Request", back_populates="attachments")


class Notification(Base):
    """Foydalanuvchi uchun bildirishnoma (push)."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(String(300), nullable=False)
    from_name = Column(String(120), nullable=True)   # kim yuborgani
    link = Column(String(255), default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=tashkent_now)


class MenuItem(Base):
    """Menyu taomi (qo'lda kiritiladi yoki iiko'dan sinxron). Stop-list uchun."""
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    ext_id = Column(String(120), nullable=True, index=True)   # iiko productId (GUID)
    is_active = Column(Boolean, default=True)


class StopEntry(Base):
    """Filial stop-listi: qaysi taom, qaysi filialda to'xtatilgan va sababi."""
    __tablename__ = "stop_entries"
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    reason = Column(String(40), nullable=False, index=True)   # sabab kaliti
    # yozuv qayerdan keldi. Standart 'manual' — odam yaratgan yozuv; iiko
    # sinxronizatsiyasi o'z yozuvlariga 'iiko' ni aniq qo'yadi.
    source = Column(String(10), default="manual", nullable=False, index=True)
    comment = Column(Text, default="")               # filial izohi
    supply_comment = Column(Text, default="")         # Снабжение izohi
    # Снабжение stop sababini tasdiqladimi (ДА / НЕТ)
    supply_confirmed = Column(Boolean, default=False, nullable=False, index=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=tashkent_now, index=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, nullable=True)   # stopdan olingan vaqti (tarix)

    branch = relationship("Branch")
    menu_item = relationship("MenuItem")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    confirmer = relationship("User", foreign_keys=[confirmed_by])


class IikoSync(Base):
    """iiko sinxronizatsiyasining umumiy holati va qulfi (bitta qator, id=1).

    Ilova bir nechta worker'da ishlaydi (WEB_CONCURRENCY) — shu qator orqali
    bir vaqtda faqat bitta worker sync qiladi."""
    __tablename__ = "iiko_sync"
    id = Column(Integer, primary_key=True)
    lock_owner = Column(String(64), default="")     # qulfni olgan worker
    lock_until = Column(DateTime, nullable=True)    # qulf shu vaqtgacha amal qiladi
    last_run_at = Column(DateTime, nullable=True)
    last_ok = Column(Boolean, default=True)
    last_error = Column(Text, default="")
    last_added = Column(Integer, default=0)
    last_resolved = Column(Integer, default=0)


class IikoWebhookEvent(Base):
    """iiko webhook'idan kelgan xom hodisa.

    iiko stop-list o'zgarganda o'zi xabar yuboradi — buning uchun access_token
    kerak emas, shuning uchun apiKey ishlamayotgan holatda ham ishlaydi.

    Payload aynan qanday ko'rinishda kelishi hujjatlarda to'liq yozilmagan
    (to'liq ro'yxatmi yoki faqat o'zgargan pozitsiyalarmi — noma'lum), shuning
    uchun avval XOM holida saqlaymiz. Real hodisani ko'rgach tahlil mantiqi
    yoziladi: noto'g'ri taxmin butun stop-listni tozalab yuborishi mumkin."""
    __tablename__ = "iiko_webhook_events"
    id = Column(Integer, primary_key=True)
    received_at = Column(DateTime, default=tashkent_now, index=True)
    event_type = Column(String(64), default="", index=True)
    org_id = Column(String(64), default="")
    terminal_group_id = Column(String(64), default="", index=True)
    authorized = Column(Boolean, default=False)   # token to'g'ri keldimi
    note = Column(String(200), default="")        # tahlil izohi / xato sababi
    body = Column(Text, default="")               # xom JSON (kesilgan)


class IikoWebhookSkip(Base):
    """Jurnalga yozilmagan hodisalar sanog'i (zakaz, rezerv, smena).

    Sanoq nega bazada: ilova bir nechta worker'da ishlaydi (WEB_CONCURRENCY=2),
    xotiradagi sanoq har bir worker'da alohida edi va /api/iiko/webhook-log
    tasodifan qaysi worker'ga tushsa o'shaning sanog'ini ko'rsatardi — son goh
    o'sib, goh kamayib turardi. Endi hamma worker bitta qatorni oshiradi."""
    __tablename__ = "iiko_webhook_skips"
    event_type = Column(String(64), primary_key=True)
    n = Column(Integer, default=0)
    last_at = Column(DateTime, nullable=True)      # oxirgi marta qachon kelgan
