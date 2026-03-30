"""Auth router: register, login, me endpoints and get_current_user dependency."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from cashflow_engine.auth import models, security, store

router = APIRouter(prefix="/auth", tags=["auth"])
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
_TIER_RANK = {"free": 0, "pro": 1}


def get_current_user(token: str = Depends(_oauth2_scheme)) -> models.User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = security.decode_token(token)
    except JWTError:
        raise credentials_exc
    user = store.get_user_by_id(user_id)
    if user is None:
        raise credentials_exc
    return user


def require_tier(tier: str):
    """Return a dependency that enforces a minimum subscription tier."""
    def _check(current_user: models.User = Depends(get_current_user)) -> models.User:
        if _TIER_RANK.get(current_user.tier, 0) < _TIER_RANK.get(tier, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient subscription tier",
            )
        return current_user
    return _check


@router.post("/register", response_model=models.UserResponse, status_code=status.HTTP_201_CREATED)
def register(req: models.RegisterRequest) -> models.UserResponse:
    if store.get_user_by_email(req.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = models.User(
        id=str(uuid.uuid4()),
        email=req.email,
        hashed_password=security.hash_password(req.password),
        tier=req.tier,
        created_at=datetime.now(timezone.utc),
    )
    store.create_user(user)
    return models.UserResponse(id=user.id, email=user.email, tier=user.tier, created_at=user.created_at)


@router.post("/login", response_model=models.TokenResponse)
def login(req: models.LoginRequest) -> models.TokenResponse:
    user = store.get_user_by_email(req.email)
    if user is None or not security.verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return models.TokenResponse(access_token=security.create_access_token(user.id))


@router.get("/me", response_model=models.UserResponse)
def me(current_user: models.User = Depends(get_current_user)) -> models.UserResponse:
    return models.UserResponse(
        id=current_user.id,
        email=current_user.email,
        tier=current_user.tier,
        created_at=current_user.created_at,
    )
