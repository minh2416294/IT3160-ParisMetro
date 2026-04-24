from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.app.database import get_db_connection
from backend.app.schemas.auth import LoginRequest, Token
from backend.app.services.auth import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(req: LoginRequest) -> Token:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT hashed_password FROM admin WHERE username = ?",
            (req.username,),
        ).fetchone()

    if row is None or not verify_password(req.password, row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token, expires_in = create_access_token(subject=req.username)
    return Token(access_token=token, expires_in=expires_in)
