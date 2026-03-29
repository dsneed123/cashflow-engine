"""FastAPI application exposing cashflow engine endpoints."""

from __future__ import annotations

from fastapi import FastAPI

from cashflow_engine.core.engine import CashflowEngine

app = FastAPI(title="Cashflow Engine", version="0.1.0")
_engine = CashflowEngine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status() -> dict:
    return _engine.status()


@app.post("/run-cycle")
def run_cycle() -> dict:
    return _engine.run_cycle()
