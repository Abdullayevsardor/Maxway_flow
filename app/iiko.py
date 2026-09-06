"""iikoCloud API klienti (api-ru.iiko.services).

Faqat o'qiydi: token, tashkilotlar, terminal guruhlar, stop-list, nomenklatura.
Bazaga ham, telegramga ham tegmaydi — sinxronizatsiya mantiqi main.py da.

Ikki xil avtorizatsiya bor va kalit turi qaysi biri ekanini iiko o'zi aytadi:

  v1  /api/1/access_token   — faqat {"apiLogin": ...}  (oddiy kalit)
  v2  /api/v2/access_token  — {"apiKey", "appId", "clientSecret"}  (marketplace
      ilovasi sifatida ro'yxatdan o'tgan kalit)

appId + clientSecret berilgan bo'lsa v2, aks holda v1 ishlatiladi.

Sozlash (env yoki loyiha ildizidagi iiko_login.txt fayli):
    MAXWAY_IIKO_LOGIN          — apiLogin / apiKey
    MAXWAY_IIKO_APP_ID         — appId (GUID), faqat v2 uchun
    MAXWAY_IIKO_CLIENT_SECRET  — clientSecret, faqat v2 uchun
    MAXWAY_IIKO_BASE           — API manzili (standart: https://api-ru.iiko.services)

iiko_login.txt bitta qator (faqat kalit) yoki `kalit=qiymat` qatorlari bo'lishi
mumkin, masalan:

    apiKey=5a1d...
    appId=00000000-0000-0000-0000-000000000000
    clientSecret=...

Token 1 soat yashaydi — ichkarida keshlanadi va muddati tugagach avtomatik
yangilanadi. Nomenklatura ham keshlanadi (har 2 daqiqada qayta yuklamaslik uchun).
"""
import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

DEFAULT_BASE = "https://api-ru.iiko.services"
TOKEN_TTL = timedelta(minutes=50)      # iiko'da token 1 soat — biroz zaxira bilan
NOMENCLATURE_TTL = timedelta(hours=6)  # menyu kam o'zgaradi
NOMENCLATURE_MIN_GAP = timedelta(minutes=10)  # notanish GUID uchun qayta yuklash chegarasi


class IikoError(Exception):
    """iiko API javob bermadi yoki xato qaytardi."""


def _read_credentials_file() -> dict:
    """iiko_login.txt ni o'qiydi. Bitta qator — apiKey; `kalit=qiymat` qatorlari
    bo'lsa apiKey/appId/clientSecret ajratib olinadi."""
    raw = ""
    for name in ("iiko_login.txt", "../iiko_login.txt"):
        try:
            with open(name, encoding="utf-8") as f:
                raw = f.read()
            break
        except FileNotFoundError:
            continue
    out = {}
    lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.strip().startswith("#")]
    if len(lines) == 1 and "=" not in lines[0]:
        return {"apikey": lines[0]}
    for line in lines:
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().lower()] = v.strip()
    # eski format: MAXWAY_IIKO_LOGIN=xxx
    if "apikey" not in out:
        for k in ("apilogin", "maxway_iiko_login", "login"):
            if k in out:
                out["apikey"] = out[k]
                break
    return out


def get_credentials() -> dict:
    """{"api_key", "app_id", "client_secret"} — env fayldan ustun turadi."""
    f = _read_credentials_file()
    return {
        "api_key": os.environ.get("MAXWAY_IIKO_LOGIN", "").strip() or f.get("apikey", ""),
        "app_id": os.environ.get("MAXWAY_IIKO_APP_ID", "").strip() or f.get("appid", ""),
        "client_secret": (os.environ.get("MAXWAY_IIKO_CLIENT_SECRET", "").strip()
                          or f.get("clientsecret", "")),
    }


def get_iiko_login() -> str:
    """apiLogin / apiKey."""
    return get_credentials()["api_key"]


def iiko_enabled() -> bool:
    """apiKey berilganmi — sync ishga tushishi uchun shart."""
    return bool(get_iiko_login())


class IikoClient:
    """Bitta apiLogin bo'yicha klient. Thread'lar orasida bo'lishish xavfsiz."""

    def __init__(self, api_login: str = "", base: str = "", timeout: int = 30,
                 app_id: str = "", client_secret: str = ""):
        creds = get_credentials()
        self.api_login = api_login or creds["api_key"]
        self.app_id = app_id or creds["app_id"]
        self.client_secret = client_secret or creds["client_secret"]
        self.base = (base or os.environ.get("MAXWAY_IIKO_BASE", DEFAULT_BASE)).rstrip("/")
        self.timeout = timeout
        self._lock = threading.Lock()
        self._token = ""
        self._token_at = None
        self._names = {}       # {org_id: {product_id: nomi}}
        self._names_at = {}    # {org_id: oxirgi yuklangan vaqt}

    # ---------- past daraja ----------
    def _raw_post(self, path: str, payload: dict, token: str = "") -> dict:
        url = f"{self.base}{path}"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            raise IikoError(f"{path}: HTTP {e.code} — {body or e.reason}") from e
        except Exception as e:
            raise IikoError(f"{path}: {e}") from e

    def _request_token(self) -> dict:
        """Kalit turiga qarab v2 yoki v1 avtorizatsiyasi.

        appId + clientSecret berilgan bo'lsa — darhol v2. Aks holda v1 sinaladi;
        iiko «bu kalit v2 talab qiladi» desa — tushunarli xato beramiz."""
        if self.app_id and self.client_secret:
            return self._raw_post("/api/v2/access_token", {
                "apiKey": self.api_login,
                "appId": self.app_id,
                "clientSecret": self.client_secret,
            })
        try:
            return self._raw_post("/api/1/access_token", {"apiLogin": self.api_login})
        except IikoError as e:
            if "/api/v2/access_token" in str(e):
                raise IikoError(
                    "Bu kalit marketplace ilovasi apiKey'i — /api/1/access_token "
                    "unga token bermaydi. Ikki yo'ldan biri kerak: "
                    "(1) iikoWeb'dan oddiy apiLogin olib MAXWAY_IIKO_LOGIN ga qo'yish "
                    "— qolgan hammasi shundayligicha ishlaydi; yoki "
                    "(2) shu apiKey uchun appId (GUID) va clientSecret ni "
                    "MAXWAY_IIKO_APP_ID / MAXWAY_IIKO_CLIENT_SECRET ga yozish "
                    "(yoki iiko_login.txt ga appId=... / clientSecret=... qatorlari)."
                ) from e
            raise

    def token(self, force: bool = False) -> str:
        """Keshlangan token; muddati tugagan bo'lsa yangisini oladi."""
        with self._lock:
            fresh = (self._token and self._token_at
                     and datetime.utcnow() - self._token_at < TOKEN_TTL)
            if fresh and not force:
                return self._token
        if not self.api_login:
            raise IikoError("apiKey berilmagan (MAXWAY_IIKO_LOGIN yoki iiko_login.txt)")
        res = self._request_token()
        tok = res.get("token", "")
        if not tok:
            raise IikoError("access_token javobida token yo'q")
        with self._lock:
            self._token = tok
            self._token_at = datetime.utcnow()
        return tok

    def post(self, path: str, payload: dict) -> dict:
        """Tokenli POST. 401 kelsa tokenni bir marta yangilab qayta uradi."""
        try:
            return self._raw_post(path, payload, self.token())
        except IikoError as e:
            if "HTTP 401" not in str(e):
                raise
            return self._raw_post(path, payload, self.token(force=True))

    # ---------- ma'lumotlar ----------
    def organizations(self) -> list:
        """[{id, name}, ...]"""
        res = self.post("/api/1/organizations",
                        {"returnAdditionalInfo": False, "includeDisabled": False})
        return res.get("organizations", []) or []

    def terminal_groups(self, org_ids: list) -> dict:
        """{organizationId: [{id, name, address}, ...]}"""
        if not org_ids:
            return {}
        res = self.post("/api/1/terminal_groups", {"organizationIds": list(org_ids)})
        out = {}
        for block in res.get("terminalGroups", []) or []:
            out[block.get("organizationId", "")] = block.get("items", []) or []
        return out

    def stop_lists(self, org_ids: list) -> dict:
        """{terminalGroupId: {productId: balance}} — hozir stopda turgan pozitsiyalar.

        iiko sabab (причина) bermaydi, faqat productId va qoldiq (balance)."""
        if not org_ids:
            return {}
        res = self.post("/api/1/stop_lists", {"organizationIds": list(org_ids)})
        out = {}
        for block in res.get("terminalGroupStopLists", []) or []:
            for tg in block.get("items", []) or []:
                tg_id = tg.get("terminalGroupId", "")
                if not tg_id:
                    continue
                items = {}
                for it in tg.get("items", []) or []:
                    pid = it.get("productId")
                    if pid:
                        items[pid] = it.get("balance")
                out[tg_id] = items
        return out

    def product_names(self, org_id: str, force: bool = False) -> dict:
        """{productId: nomi} — keshlangan nomenklatura.

        To'liq menyu sinxronizatsiyasi qilinmaydi: bu kesh faqat stopga tushgan
        GUID dan taom nomini topish uchun kerak."""
        with self._lock:
            at = self._names_at.get(org_id)
            if not force and at and datetime.utcnow() - at < NOMENCLATURE_TTL:
                return self._names.get(org_id, {})
        res = self.post("/api/1/nomenclature", {"organizationId": org_id})
        names = {}
        for p in res.get("products", []) or []:
            pid = p.get("id")
            if pid:
                names[pid] = (p.get("name") or p.get("code") or "").strip() or pid[:8]
        with self._lock:
            self._names[org_id] = names
            self._names_at[org_id] = datetime.utcnow()
        return names

    def resolve_names(self, org_ids: list, product_ids) -> dict:
        """Kerakli GUID lar uchun nomlar. Notanish GUID chiqsa nomenklaturani
        qayta yuklaydi (lekin NOMENCLATURE_MIN_GAP dan tez-tez emas — yangi taom
        qo'shilgan bo'lishi mumkin, iiko'ni ortiqcha yuklamaymiz)."""
        need = set(product_ids or ())
        names = {}
        for oid in org_ids:
            try:
                names.update(self.product_names(oid))
            except IikoError:
                continue
        missing = need - set(names)
        if missing:
            for oid in org_ids:
                with self._lock:
                    at = self._names_at.get(oid)
                    too_soon = at and datetime.utcnow() - at < NOMENCLATURE_MIN_GAP
                if too_soon:
                    continue
                try:
                    names.update(self.product_names(oid, force=True))
                except IikoError:
                    continue
        return names


_client = None
_client_lock = threading.Lock()


def get_client() -> IikoClient:
    """Butun ilova uchun bitta klient (token va nomenklatura keshi bo'lishilsin)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = IikoClient()
        return _client
