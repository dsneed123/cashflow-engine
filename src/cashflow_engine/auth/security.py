"""Password hashing and JWT token utilities."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

_DEV_SECRET = "dev-secret-change-in-production"
_MIN_SECRET_LEN = 32
_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _DEV_SECRET)
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def validate_jwt_secret(secret: str) -> None:
    """Raise ValueError if *secret* is insecure (default or too short)."""
    if secret == _DEV_SECRET:
        raise ValueError(
            "JWT_SECRET_KEY must not be the default dev value; set a secure random string."
        )
    if len(secret) < _MIN_SECRET_LEN:
        raise ValueError(
            f"JWT_SECRET_KEY must be at least {_MIN_SECRET_LEN} characters long."
        )


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
