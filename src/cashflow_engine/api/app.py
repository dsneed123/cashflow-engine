"""FastAPI application exposing cashflow engine endpoints."""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cashflow_engine.auth import models as auth_models
from cashflow_engine.auth.router import get_current_user, require_tier, router as auth_router
from cashflow_engine.core.engine import CashflowEngine
from cashflow_engine.subscriptions.router import router as subscriptions_router

app = FastAPI(title="Cashflow Engine", version="0.1.0")
app.include_router(auth_router)
app.include_router(subscriptions_router)
_engine = CashflowEngine()

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_AUTH_RATE_LIMIT = 60    # requests per minute for /auth/login and /auth/register
_DEFAULT_RATE_LIMIT = 100  # requests per minute for all other endpoints
_WINDOW = 60.0            # sliding window in seconds

_AUTH_PATHS = {"/auth/login", "/auth/register"}

_rate_store: dict[str, deque[float]] = {}
_store_lock = threading.Lock()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(client_ip: str, path: str) -> tuple[bool, int]:
    """Sliding-window rate check. Returns (allowed, retry_after_seconds)."""
    limit = _AUTH_RATE_LIMIT if path in _AUTH_PATHS else _DEFAULT_RATE_LIMIT
    key = f"{client_ip}:{path}"
    now = time.monotonic()
    cutoff = now - _WINDOW

    with _store_lock:
        if key not in _rate_store:
            _rate_store[key] = deque()
        timestamps = _rate_store[key]

        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= limit:
            retry_after = max(1, int(timestamps[0] + _WINDOW - now) + 1)
            return False, retry_after

        timestamps.append(now)
        return True, 0


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = _get_client_ip(request)
    allowed, retry_after = _check_rate_limit(client_ip, request.url.path)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests"},
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# CORS  (added after rate-limit middleware so it wraps it — outermost layer)
# ---------------------------------------------------------------------------

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status(_: auth_models.User = Depends(get_current_user)) -> dict:
    return _engine.status()


@app.post("/run-cycle")
def run_cycle(_: auth_models.User = Depends(require_tier("pro"))) -> dict:
    return _engine.run_cycle()


# ---------------------------------------------------------------------------
# Billing endpoints
# ---------------------------------------------------------------------------


class _CheckoutRequest(BaseModel):
    price_id: str


@app.post("/billing/checkout")
def billing_checkout(
    body: _CheckoutRequest,
    current_user: auth_models.User = Depends(get_current_user),
) -> dict:
    mgr = _engine.subscriptions
    if not mgr._stripe:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    subscriber = next((s for s in mgr._subscribers if s["id"] == current_user.id), None)
    if subscriber is None:
        subscriber = mgr.add_subscriber(current_user.id, current_user.email, current_user.email)
    if not subscriber.get("stripe_customer_id"):
        raise HTTPException(status_code=503, detail="Stripe customer not available")
    try:
        url = mgr.create_checkout_session(current_user.id, body.price_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"checkout_url": url}


@app.post("/billing/webhook")
async def billing_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
) -> dict:
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Stripe-Signature header required")
    payload = await request.body()
    try:
        result = _engine.subscriptions.handle_webhook(payload, stripe_signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result
