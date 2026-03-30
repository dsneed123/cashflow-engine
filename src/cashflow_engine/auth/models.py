"""Auth Pydantic models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class User(BaseModel):
    id: str
    email: str
    hashed_password: str
    tier: str = "free"
    created_at: datetime
    stripe_customer_id: str | None = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    tier: str = "free"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    tier: str
    created_at: datetime
