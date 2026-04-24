from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from backend.app.config import settings

_BCRYPT_MAX_BYTES = 72


class AuthError(Exception):
    """Raised for invalid or expired tokens."""


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password is {len(pw)} bytes; bcrypt accepts at most {_BCRYPT_MAX_BYTES}."
        )
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_minutes: int | None = None) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    minutes = expires_minutes if expires_minutes is not None else settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, minutes * 60


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AuthError(str(exc)) from exc
