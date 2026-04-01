"""Tests for JWT auth endpoints."""

import concurrent.futures
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from cashflow_engine.api.app import app
from cashflow_engine.auth import store
from cashflow_engine.auth.models import User

client = TestClient(app)


def _register(email: str, password: str = "testpass", tier: str = "free") -> dict:
    return client.post("/auth/register", json={"email": email, "password": password, "tier": tier}).json()


def _login_token(email: str, password: str = "testpass") -> str:
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


def test_register_success():
    resp = client.post("/auth/register", json={"email": "a@test.com", "password": "secret"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "a@test.com"
    assert data["tier"] == "free"
    assert "id" in data
    assert "created_at" in data
    assert "hashed_password" not in data


def test_register_custom_tier():
    resp = client.post("/auth/register", json={"email": "b@test.com", "password": "secret", "tier": "pro"})
    assert resp.status_code == 201
    assert resp.json()["tier"] == "pro"


def test_register_duplicate_email():
    payload = {"email": "c@test.com", "password": "secret"}
    client.post("/auth/register", json=payload)
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409


def test_login_success():
    _register("d@test.com", "mypassword")
    resp = client.post("/auth/login", json={"email": "d@test.com", "password": "mypassword"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password():
    _register("e@test.com", "correct")
    resp = client.post("/auth/login", json={"email": "e@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user():
    resp = client.post("/auth/login", json={"email": "nobody@test.com", "password": "x"})
    assert resp.status_code == 401


def test_me_returns_user():
    _register("f@test.com")
    token = _login_token("f@test.com")
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "f@test.com"
    assert "hashed_password" not in data


def test_me_no_token():
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_invalid_token():
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert resp.status_code == 401


def test_run_cycle_requires_auth():
    resp = client.post("/run-cycle")
    assert resp.status_code == 401


def test_run_cycle_free_user_forbidden():
    _register("g@test.com", tier="free")
    token = _login_token("g@test.com")
    resp = client.post("/run-cycle", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_run_cycle_pro_user_allowed():
    _register("g2@test.com", tier="pro")
    token = _login_token("g2@test.com")
    resp = client.post("/run-cycle", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_status_requires_auth():
    resp = client.get("/status")
    assert resp.status_code == 401


def test_status_with_auth():
    _register("h@test.com")
    token = _login_token("h@test.com")
    resp = client.get("/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ---------------------------------------------------------------------------
# Concurrent-write stress tests
# ---------------------------------------------------------------------------


def _make_user(suffix: str) -> User:
    return User(
        id=str(uuid.uuid4()),
        email=f"conc_{suffix}@test.com",
        hashed_password="x",
        created_at=datetime.now(timezone.utc),
    )


def test_create_user_concurrent_no_lost_writes():
    """Concurrent create_user calls must not lose any user records."""
    n = 20
    users = [_make_user(str(i)) for i in range(n)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(store.create_user, u) for u in users]
        for f in concurrent.futures.as_completed(futures):
            f.result()
    saved = store._load()
    assert len(saved) == n


def test_update_user_concurrent_no_corruption():
    """Concurrent update_user calls must not corrupt the store."""
    users = [_make_user(f"upd{i}") for i in range(10)]
    for u in users:
        store.create_user(u)
    updated = [u.model_copy(update={"hashed_password": "updated"}) for u in users]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(store.update_user, u) for u in updated]
        for f in concurrent.futures.as_completed(futures):
            f.result()
    saved = store._load()
    assert len(saved) == 10
    assert all(u["hashed_password"] == "updated" for u in saved)
