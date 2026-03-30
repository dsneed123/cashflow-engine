"""Tests for FastAPI endpoints."""

from fastapi.testclient import TestClient

from cashflow_engine.api.app import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status():
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "trading" in data
    assert "arbitrage" in data
    assert "subscriptions" in data


def test_run_cycle():
    client.post("/auth/register", json={"email": "api_test@example.com", "password": "testpass"})
    token = client.post(
        "/auth/login", json={"email": "api_test@example.com", "password": "testpass"}
    ).json()["access_token"]
    resp = client.post("/run-cycle", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
