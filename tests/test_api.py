"""Tests for FastAPI endpoints."""

import time
from collections import deque

import pytest
from fastapi.testclient import TestClient

from cashflow_engine.api.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_store():
    """Clear rate-limit state before and after each test to prevent cross-test pollution."""
    from cashflow_engine.api.app import _rate_store
    _rate_store.clear()
    yield
    _rate_store.clear()


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status():
    client.post("/auth/register", json={"email": "status_test@example.com", "password": "testpass"})
    token = client.post(
        "/auth/login", json={"email": "status_test@example.com", "password": "testpass"}
    ).json()["access_token"]
    resp = client.get("/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "trading" in data
    assert "arbitrage" in data
    assert "subscriptions" in data


def test_run_cycle():
    client.post("/auth/register", json={"email": "api_test@example.com", "password": "testpass", "tier": "pro"})
    token = client.post(
        "/auth/login", json={"email": "api_test@example.com", "password": "testpass"}
    ).json()["access_token"]
    resp = client.post("/run-cycle", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_rate_limit_auth_endpoint():
    """Returns 429 with Retry-After header once the auth endpoint rate limit is exceeded."""
    from cashflow_engine.api.app import _rate_store, _AUTH_RATE_LIMIT

    ip = "10.0.0.10"
    key = f"{ip}:/auth/login"
    now = time.monotonic()
    _rate_store[key] = deque([now] * _AUTH_RATE_LIMIT)

    resp = client.post(
        "/auth/login",
        json={"email": "rl@example.com", "password": "wrong"},
        headers={"X-Forwarded-For": ip},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) >= 1


def test_rate_limit_other_endpoint():
    """Returns 429 with Retry-After header once the default rate limit is exceeded."""
    from cashflow_engine.api.app import _rate_store, _DEFAULT_RATE_LIMIT

    ip = "10.0.0.11"
    key = f"{ip}:/health"
    now = time.monotonic()
    _rate_store[key] = deque([now] * _DEFAULT_RATE_LIMIT)

    resp = client.get("/health", headers={"X-Forwarded-For": ip})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) >= 1


def test_rate_limit_not_triggered_below_threshold():
    """Requests below the limit are not rate-limited."""
    resp = client.get("/health", headers={"X-Forwarded-For": "10.0.0.20"})
    assert resp.status_code == 200


def test_cors_headers_present():
    """CORS Access-Control-Allow-Origin header is included in responses."""
    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers
