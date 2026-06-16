"""Autentifikatsiya: parol hashlash va JWT token (cookie orqali)."""
from datetime import datetime, timedelta
from typing import Optional

import os
import hmac
import base64
import hashlib

import jwt
from fastapi import Depends, Request, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from . import models

SECRET_KEY = os.environ.get("MAXWAY_SECRET", "MAXWAY-secret-key-uni-productionda-ozgartiring-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 kun
COOKIE_NAME = "maxway_token"

# Parolni hashlash — Python'ning standart hashlib kutubxonasi (PBKDF2-SHA256).
# Hech qanday tashqi kutubxona kerak emas, har qanday Python versiyasida ishlaydi.
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Parolni xavfsiz formatda hashlaydi: pbkdf2_sha256$iter$salt$hash"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(plain: str, hashed: str) -> bool:
    """Kiritilgan parolni saqlangan hash bilan solishtiradi."""
    try:
        algo, iters, salt_b64, hash_b64 = hashed.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> Optional[models.User]:
    """Cookie'dagi token bo'yicha foydalanuvchini qaytaradi (yoki None)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = decode_token(token)
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> models.User:
    """Tizimga kirishni majburiy qiladi."""
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Avval tizimga kiring",
        )
    return user
