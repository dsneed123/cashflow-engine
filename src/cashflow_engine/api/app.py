"""FastAPI application exposing cashflow engine endpoints."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from cashflow_engine.auth import models as auth_models
from cashflow_engine.auth.router import get_current_user, router as auth_router
from cashflow_engine.core.engine import CashflowEngine

app = FastAPI(title="Cashflow Engine", version="0.1.0")
app.include_router(auth_router)
_engine = CashflowEngine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status(_: auth_models.User = Depends(get_current_user)) -> dict:
    return _engine.status()


@app.post("/run-cycle")
def run_cycle(_: auth_models.User = Depends(get_current_user)) -> dict:
    return _engine.run_cycle()
