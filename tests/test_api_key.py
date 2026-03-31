"""Tests for API key authentication endpoints and tier enforcement."""

from fastapi.testclient import TestClient

from cashflow_engine.api.app import app

client = TestClient(app)


def _register(email: str, password: str = "testpass", tier: str = "free") -> dict:
    return client.post("/auth/register", json={"email": email, "password": password, "tier": tier}).json()


def _login_token(email: str, password: str = "testpass") -> str:
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _auth_headers(email: str) -> dict:
    return {"Authorization": f"Bearer {_login_token(email)}"}


# ---------------------------------------------------------------------------
# API key generation
# ---------------------------------------------------------------------------


def test_generate_api_key_pro_user():
    _register("pro1@test.com", tier="pro")
    resp = client.post("/auth/api-key", headers=_auth_headers("pro1@test.com"))
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" in data
    assert len(data["api_key"]) > 20


def test_generate_api_key_free_user_forbidden():
    _register("free1@test.com", tier="free")
    resp = client.post("/auth/api-key", headers=_auth_headers("free1@test.com"))
    assert resp.status_code == 403


def test_generate_api_key_unauthenticated():
    resp = client.post("/auth/api-key")
    assert resp.status_code == 401


def test_generate_api_key_replaces_existing():
    _register("pro2@test.com", tier="pro")
    headers = _auth_headers("pro2@test.com")
    first = client.post("/auth/api-key", headers=headers).json()["api_key"]
    second = client.post("/auth/api-key", headers=headers).json()["api_key"]
    assert first != second


# ---------------------------------------------------------------------------
# API key retrieval
# ---------------------------------------------------------------------------


def test_get_api_key_returns_key():
    _register("pro3@test.com", tier="pro")
    headers = _auth_headers("pro3@test.com")
    created_key = client.post("/auth/api-key", headers=headers).json()["api_key"]
    resp = client.get("/auth/api-key", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["api_key"] == created_key


def test_get_api_key_not_found_when_none():
    _register("free2@test.com", tier="free")
    resp = client.get("/auth/api-key", headers=_auth_headers("free2@test.com"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API key revocation
# ---------------------------------------------------------------------------


def test_revoke_api_key():
    _register("pro4@test.com", tier="pro")
    headers = _auth_headers("pro4@test.com")
    client.post("/auth/api-key", headers=headers)
    resp = client.delete("/auth/api-key", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "API key revoked"
    # key should be gone
    resp2 = client.get("/auth/api-key", headers=headers)
    assert resp2.status_code == 404


def test_revoke_api_key_unauthenticated():
    resp = client.delete("/auth/api-key")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Authentication via API key header
# ---------------------------------------------------------------------------


def test_authenticate_with_api_key():
    _register("pro5@test.com", tier="pro")
    token = _login_token("pro5@test.com")
    api_key = client.post("/auth/api-key", headers={"Authorization": f"Bearer {token}"}).json()["api_key"]

    resp = client.get("/auth/me", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["email"] == "pro5@test.com"


def test_authenticate_with_invalid_api_key():
    resp = client.get("/auth/me", headers={"X-API-Key": "invalid-key-xyz"})
    assert resp.status_code == 401


def test_api_key_can_access_protected_endpoint():
    _register("pro6@test.com", tier="pro")
    token = _login_token("pro6@test.com")
    api_key = client.post("/auth/api-key", headers={"Authorization": f"Bearer {token}"}).json()["api_key"]

    resp = client.get("/status", headers={"X-API-Key": api_key})
    assert resp.status_code == 200


def test_jwt_takes_priority_over_api_key():
    """When both headers present, JWT auth wins."""
    _register("pro7@test.com", tier="pro")
    _register("other@test.com", tier="free")
    token = _login_token("pro7@test.com")
    # generate an API key for other user
    other_token = _login_token("other@test.com")
    # other user has no key yet; just test that JWT user identity is used
    resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-API-Key": "ignored-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "pro7@test.com"


def test_api_key_auth_enforces_tier_via_require_tier():
    """API key for a free user is denied on pro-only endpoints."""
    # Manually craft a free user with an API key via direct store manipulation
    _register("free3@test.com", tier="free")
    # free users can't generate keys via endpoint, so use store directly
    from cashflow_engine.auth import store
    user = store.get_user_by_email("free3@test.com")
    user.api_key = store.generate_api_key()
    store.update_user(user)

    resp = client.post("/run-cycle", headers={"X-API-Key": user.api_key})
    assert resp.status_code == 403
