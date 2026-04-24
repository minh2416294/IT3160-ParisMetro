from __future__ import annotations

import bcrypt

_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password is {len(pw)} bytes; bcrypt accepts at most {_BCRYPT_MAX_BYTES}."
        )
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
