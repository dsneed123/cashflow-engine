"""Password hashing and JWT token utilities."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production")
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:72]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode("utf-8")[:72]
    return bcrypt.checkpw(truncated, hashed.encode("utf-8"))


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": subject, "exp": expire}, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> str:
    """Decode JWT and return the subject (user id). Raises JWTError on failure."""
    payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    sub = payload.get("sub")
    if sub is None:
        raise JWTError("Missing sub claim")
    return sub
